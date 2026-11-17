from sqlalchemy import String,Float,Boolean,Integer,ForeignKey,JSON,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(120),unique=True)
    role:Mapped[str]=mapped_column(String(20))
    password_hash:Mapped[str]=mapped_column(String(200))
class Student(Base):
    __tablename__='students'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50),unique=True)
    name:Mapped[str]=mapped_column(String(80))
    campus:Mapped[str]=mapped_column(String(50))
    group:Mapped[str]=mapped_column(String(20))
    score:Mapped[float|None]=mapped_column(Float,nullable=True)
    absent:Mapped[bool]=mapped_column(Boolean,default=False)
class Plan(Base):
    __tablename__='plans'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(120),unique=True)
    campus:Mapped[str]=mapped_column(String(50),default='全部')
    exclude_absent:Mapped[bool]=mapped_column(Boolean,default=True)
    description:Mapped[str]=mapped_column(Text,default='')
class Report(Base):
    __tablename__='reports'
    id:Mapped[int]=mapped_column(primary_key=True)
    plan_id:Mapped[int]=mapped_column(ForeignKey('plans.id'))
    status:Mapped[str]=mapped_column(String(20),default='queued')
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    conclusion:Mapped[str]=mapped_column(Text,default='')
    published:Mapped[bool]=mapped_column(Boolean,default=False)
    supplement_snapshot:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    created_at:Mapped[str]=mapped_column(String(40))
class SupplementDraw(Base):
    __tablename__='supplement_draws'
    __table_args__=(UniqueConstraint('plan_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    plan_id:Mapped[int]=mapped_column(ForeignKey('plans.id'))
    status:Mapped[str]=mapped_column(String(20),default='pending')
    seed:Mapped[str]=mapped_column(String(64))
    design:Mapped[dict]=mapped_column(JSON)
    checksum:Mapped[str]=mapped_column(String(64))
    created_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40))
    issued_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
class SupplementSample(Base):
    __tablename__='supplement_samples'
    __table_args__=(UniqueConstraint('plan_id','student_id'),UniqueConstraint('draw_id','student_id'))
    id:Mapped[int]=mapped_column(primary_key=True)
    draw_id:Mapped[int]=mapped_column(ForeignKey('supplement_draws.id'))
    plan_id:Mapped[int]=mapped_column(ForeignKey('plans.id'))
    student_id:Mapped[int]=mapped_column(ForeignKey('students.id'))
    code:Mapped[str]=mapped_column(String(50))
    name:Mapped[str]=mapped_column(String(80))
    campus:Mapped[str]=mapped_column(String(50))
    group:Mapped[str]=mapped_column(String(20))
    stratum:Mapped[str]=mapped_column(String(120))
    inclusion_probability:Mapped[float]=mapped_column(Float)
    selection_rank:Mapped[int]=mapped_column(Integer)
    outcome:Mapped[str]=mapped_column(String(20),default='awaiting')
    retest_score:Mapped[float|None]=mapped_column(Float,nullable=True)
    responded_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
    response_by:Mapped[str]=mapped_column(String(120),default='')
    response_version:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[str]=mapped_column(String(40))
class SupplementResponse(Base):
    __tablename__='supplement_responses'
    id:Mapped[int]=mapped_column(primary_key=True)
    sample_id:Mapped[int]=mapped_column(ForeignKey('supplement_samples.id'))
    outcome:Mapped[str]=mapped_column(String(20))
    retest_score:Mapped[float|None]=mapped_column(Float,nullable=True)
    note:Mapped[str]=mapped_column(Text,default='')
    actor:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40))
class Audit(Base):
    __tablename__='audit_logs'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(String(200))
    status:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[str]=mapped_column(String(40))
