"""메모리 어휘. 서버 시작 시 DB에서 읽고, API-004로 다시 읽는다 (02_BACKEND.md 1장 "vocab·job_relation은 서버 시작 시 메모리 로드")."""
from dataclasses import dataclass, field

from psycopg_pool import AsyncConnectionPool

from app.core.industry import FamilyIndex, build_family_index
from app.core.matching import RelationIndex, build_relation_index
from app.core.slot_filling import SlotVocab
from app.repositories.vocab import VocabRows, load_vocab_rows


@dataclass(frozen=True)
class Vocab:
    slot_vocab: SlotVocab                      # 슬롯필링 선택지 ('임시' 직무 제외)
    relations: RelationIndex
    families: FamilyIndex
    job_aliases: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=dict)
    companies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """DB 적재 전. 직무나 산업 어휘가 없으면 슬롯필링을 할 수 없다."""
        return not self.slot_vocab.jobs or not self.slot_vocab.user_industries


def build_vocab(rows: VocabRows) -> Vocab:
    return Vocab(
        slot_vocab=SlotVocab({j: f for j, f, temporary in rows.jobs if not temporary}, tuple(rows.industries)),
        relations=build_relation_index((a, b, rel) for a, b, rel, _ in rows.job_relations),
        families=build_family_index(rows.industry_families),
        job_aliases=dict(rows.job_aliases), companies=dict(rows.companies), categories=dict(rows.categories))


EMPTY_VOCAB = build_vocab(VocabRows())


class VocabStore:
    """현재 어휘 하나를 들고 있다. 재로드가 실패하면 이전 어휘를 그대로 둔다."""

    def __init__(self, vocab: Vocab = EMPTY_VOCAB):
        self.current = vocab

    async def reload(self, pool: AsyncConnectionPool) -> dict[str, int]:
        async with pool.connection() as conn:
            rows = await load_vocab_rows(conn)
        self.current = build_vocab(rows)
        return rows.counts()
