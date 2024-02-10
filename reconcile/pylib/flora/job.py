from typing import Any, ClassVar

from reconcile.pylib.base import Base


class Job(Base):
    rec_lb: ClassVar[str] = "dwc:recordedBy"
    id_lb: ClassVar[str] = "dwc:identifiedBy"
    rec_match: ClassVar[list[str]] = Base.get_aliases(rec_lb, """dwc:recordedByName""")
    id_match: ClassVar[list[str]] = Base.get_aliases(id_lb)

    @classmethod
    def reconcile(
        cls, traiter: dict[str, Any], other: dict[str, Any], text: str
    ) -> dict[str, Any]:
        o_rec = cls.search(other, cls.rec_match)
        o_id = cls.search(other, cls.id_match)

        obj = {}

        # Just use whatever is in the OpenAI output
        if o_rec:
            obj[cls.rec_lb] = o_rec

        if o_id:
            obj[cls.id_lb] = o_id

        return obj
