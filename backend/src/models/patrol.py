from sqlalchemy import String, JSON, Double, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class PatrolBatch(Base):
    """无标签待巡批次：只有管段编号和四项测量值，没有 confirmed_leak。"""
    __tablename__ = 'patrol_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)


class Dispatch(Base):
    """巡检派单：保存当时的规则快照、输入指纹与完整评分结果，创建后不再变更。

    后续新增试验或批次都不会影响已派结果——评分只依赖 rule_snapshot 与
    input_checksum 对应的输入副本，二者均完整保存在本行。
    """
    __tablename__ = 'dispatches'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    patrol_batch_id: Mapped[int] = mapped_column(ForeignKey('patrol_batches.id'))
    quota: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='issued')
    rule_snapshot: Mapped[dict] = mapped_column(JSON)
    rule_params: Mapped[dict] = mapped_column(JSON)
    input_checksum: Mapped[str] = mapped_column(String(64))
    input_records: Mapped[list] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
