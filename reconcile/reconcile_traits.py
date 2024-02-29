#!/usr/bin/env python3
import argparse
import json
import logging
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from pprint import pp
from typing import Any

from util.pylib import log

import reconcile.pylib.darwin_core as dwc
from reconcile.pylib.base import Template
from reconcile.pylib.labels.admin_unit import AdminUnit
from reconcile.pylib.labels.id_number import IdNumber
from reconcile.pylib.labels.job import Job
from reconcile.pylib.labels.locality import Locality
from reconcile.pylib.labels.record_number import RecordNumber
from reconcile.pylib.labels.sex import Sex
from reconcile.pylib.labels.taxon_assoc import TaxonAssociation
from reconcile.pylib.labels.taxon_auth import TaxonAuthority
from reconcile.pylib.labels.taxon_name import TaxonName
from reconcile.pylib.labels.taxon_rank import TaxonRank
from reconcile.pylib.traiter.coordinate_precision import CoordinatePrecision
from reconcile.pylib.traiter.coordinate_uncertainty import CoordinateUncertainty
from reconcile.pylib.traiter.decimal_latitude import DecimalLatitude
from reconcile.pylib.traiter.decimal_longitude import DecimalLongitude
from reconcile.pylib.traiter.event_date import EventDate
from reconcile.pylib.traiter.geodetic_datum import GeodeticDatum
from reconcile.pylib.traiter.habitat import Habitat
from reconcile.pylib.traiter.maximum_elevation import MaximumElevationInMeters
from reconcile.pylib.traiter.minimum_elevation import MinimumElevationInMeters
from reconcile.pylib.traiter.verbatim_coordinates import VerbatimCoordinates
from reconcile.pylib.traiter.verbatim_elevation import VerbatimElevation
from reconcile.pylib.traiter.verbatim_system import VerbatimCoordinateSystem
from reconcile.pylib.util import clean_key


class Verbose(IntEnum):
    QUIET = 0
    ERRORS = 1
    INPUT = 2
    FIELDS = 3


@dataclass
class Row:
    stem: str
    text: str = ""
    traiter: dict[str, Any] = field(default_factory=dict)
    openai: dict[str, Any] = field(default_factory=dict)
    reconciled: dict[str, Any] = field(default_factory=dict)
    missed: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    def get_text(self, text_dir):
        path = text_dir / f"{self.stem}.txt"
        with path.open() as f:
            text = f.read()
        self.text = compress(text)

    def get_traiter(self, traiter_dir):
        path = traiter_dir / f"{self.stem}.json"
        with path.open() as f:
            self.traiter = json.load(f)

    def get_openai(self, openai_dir):
        path = openai_dir / f"{self.stem}.json"
        with path.open() as f:
            openai = json.load(f)

        new = {}
        for key, value in openai.items():
            new[key] = value
            if isinstance(value, dict):
                new |= dict(value.items())

        self.openai = {clean_key(k): v for k, v in new.items()}

    def reconcile(self, template):
        for func in template.actions:
            try:
                self.reconciled |= func(self.traiter, self.openai, self.text)
            except ValueError as err:
                self.errors.append(str(err))

        self.missed = set(self.openai.keys()) - set(self.reconciled.keys())

    def save_traits(self, parsed_dir):
        keys = sorted(self.reconciled.keys())
        self.reconciled = {k: self.reconciled[k] for k in keys}
        path = parsed_dir / f"{self.stem}.json"
        with path.open("w") as f:
            json.dump(self.reconciled, f, indent=4)

    def verbose(self, verbose):
        if (verbose == Verbose.ERRORS and self.errors) or (verbose > Verbose.ERRORS):
            print("=" * 80)
            print(self.stem)
            print()

        if verbose >= Verbose.ERRORS and self.errors:
            print("---- Errors ", "-" * 40)
            for error in self.errors:
                print(error)
            print()

        if verbose >= Verbose.INPUT:
            print("---- Text ", "-" * 40)
            print(self.text)
            print()
            print("---- Traiter ", "-" * 40)
            pp(self.traiter)
            print()
            print("---- OpenAI ", "-" * 40)
            pp(self.openai)
            print()
            print("---- Reconciled ", "-" * 40)
            pp(self.reconciled)
            print()


def main():
    log.started()
    args = parse_args()

    text_stems = {p.stem for p in args.text_dir.glob("*")}
    traiter_stems = {p.stem for p in args.traiter_dir.glob("*")}
    openai_stems = {p.stem for p in args.openai_dir.glob("*")}

    args.formatted_dir.mkdir(parents=True, exist_ok=True)

    stems = sorted(text_stems & openai_stems & traiter_stems)

    msg = (
        f"Text: {len(text_stems)}, "
        f"Traiter: {len(traiter_stems)}, "
        f"OpenAI: {len(openai_stems)}, "
        f"Intersection: {len(stems)}, "
        f"All numbers the same: "
        f"{len(text_stems) == len(openai_stems) == len(stems) == len(traiter_stems)}."
    )
    logging.info(msg)

    if args.stem:
        stems = [s for s in stems if s == args.stem]

    if args.count:
        count_keys(args.openai_dir)

    else:
        template = Template(
            EventDate,
            MinimumElevationInMeters,
            MaximumElevationInMeters,
            VerbatimElevation,
            Habitat,
            DecimalLatitude,
            DecimalLongitude,
            CoordinateUncertainty,
            CoordinatePrecision,
            GeodeticDatum,
            VerbatimCoordinateSystem,
            VerbatimCoordinates,
            AdminUnit,
            Job,  # Put Job before RecordNumber because Job can fill RecordNumber
            RecordNumber,  # Put after Job, so it can override whatever Job did
            IdNumber,
            Locality,
            Sex,
            TaxonAssociation,
            TaxonAuthority,
            TaxonName,
            TaxonRank,
        )

        total_errors = 0
        rows = []

        for stem in stems:
            row = Row(stem=stem)
            rows.append(row)

            row.get_text(args.text_dir)
            row.get_traiter(args.traiter_dir)
            row.get_openai(args.openai_dir)

            row.reconcile(template)

            row.save_traits(args.formatted_dir)

            row.verbose(args.verbose)

            total_errors += len(row.errors)
            if total_errors > args.max_errors:
                msg = f"Max errors of {args.max_errors} exceeded"
                logging.error(msg)
                sys.exit(1)

        show_missed_keys(rows, args.verbose)

        msg = f"Total errors: {total_errors}"
        logging.info(msg)

    log.finished()


def show_missed_keys(rows, verbose):
    if verbose < Verbose.FIELDS:
        return

    missed = defaultdict(int)
    for row in rows:
        for m in row.missed:
            missed[m] += 1

    missed = dict(sorted(missed.items()))
    print("---- Missed Keys ", "-" * 40)
    pp(missed)
    print()

    valid = {k: v for k, v in missed.items() if k in dwc.CORE}
    print("---- Missed DwC Keys ", "-" * 40)
    pp(valid)
    print()


def count_keys(dir_) -> dict[str, int]:
    keys = defaultdict(int)

    for path in dir_.glob("*.json"):
        with path.open() as f:
            obj = json.load(f)

        for key in obj:
            key = clean_key(key)
            keys[key] += 1

    keys = dict(sorted(keys.items()))

    valid_count = 0
    print("key,valid,count")
    for key, count in keys.items():
        valid = 1 if key in dwc.CORE else ""
        print(f"{key},{valid},{count}")
        valid_count += 1 if valid else 0

    print(f"{valid_count}/{len(keys)} valid keys")
    print(f"{len(keys) - valid_count}/{len(keys)} invalid keys")

    return keys


def compress(text: str) -> str:
    """Collapse whitespace in a string but keep lines."""
    text = [" ".join(ln.split()) for ln in text.splitlines()]
    text = "\n".join(ln for ln in text if ln)
    return text


def parse_args() -> argparse.Namespace:
    arg_parser = argparse.ArgumentParser(
        fromfile_prefix_chars="@",
        description=textwrap.dedent("""Format and validate ChatGPT results."""),
    )

    arg_parser.add_argument(
        "--text-dir",
        metavar="PATH",
        type=Path,
        required=True,
        help="""Get OCR text output files from this directory.""",
    )

    arg_parser.add_argument(
        "--openai-dir",
        metavar="PATH",
        type=Path,
        required=True,
        help="""Get OpenAI JSON files from this directory.""",
    )

    arg_parser.add_argument(
        "--traiter-dir",
        metavar="PATH",
        type=Path,
        required=True,
        help="""Get traiter JSON files from this directory.""",
    )

    arg_parser.add_argument(
        "--formatted-dir",
        metavar="PATH",
        type=Path,
        required=True,
        help="""Put the formatted result files into this directory.""",
    )

    arg_parser.add_argument(
        "--count",
        action="store_true",
        help="""Count the keys in the openAI output.""",
    )

    arg_parser.add_argument(
        "--max-errors",
        "-e",
        metavar="INT",
        type=int,
        default=999_999_999,
        help="""Allow this many errors before exiting.""",
    )

    arg_parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="""Print information for debugging.""",
    )

    arg_parser.add_argument(
        "--stem",
        help="""Use this record for debugging.""",
    )

    args = arg_parser.parse_args()
    return args


if __name__ == "__main__":
    main()
