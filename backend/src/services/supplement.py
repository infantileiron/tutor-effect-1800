"""补测抽样与总体均分估计。

设计要点：
- 抽样框在“发起补测”时冻结，按 教学点 × 原分组 分层，从缺考名册中无放回抽取固定名额。
- 每个缺考者的入选概率 pi = n_h / N_h 在抽取前写入设计并计算校验码，之后的名册修订、
  并发补分与重复执行都不会改变 pi，也不会产生第二次入选。
- 回应（responded / refused / unreachable）只追加历史，不补抽新样本。
- 点估计使用回应调整权重 N_h / r_h（层内回应与成绩无关的假设）；未回应时给出
  0–100 分取值范围内的识别区间，绝不把愿意返校的补测者当作全体缺考者。
"""
import hashlib
import json
import random
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.models.entities import Plan, Student, SupplementDraw, SupplementResponse, SupplementSample

DRAW_STATUSES = ('pending', 'drawn', 'issued')
OUTCOMES = ('awaiting', 'responded', 'refused', 'unreachable')
GROUPS = ('control', 'intervention')

ASSUMPTIONS = [
    '抽样框为发起补测时冻结的原应考名册：非缺考且当时有成绩的记录作为已观测总体，缺考记录进入补测抽样框；此后名册修订不改写冻结记录。',
    '每个 教学点 × 原分组 层内对缺考名册做无放回简单随机抽样，入选概率 π = n_h / N_h 在抽取前封存；空层 π 记为 0。',
    '点估计假设同一层内“是否回应/是否愿意返校”与补测成绩无关（MAR）；权重 N_h / r_h = 1 / (π_h × r_h / n_h)，即设计权重的回应调整，用于估计该层缺考总分。',
    '拒绝、失联、未回应与未抽中的缺考者补测分未知，只限定在 0–100 分；由此得到组均分的识别区间。',
    '补测者只是缺考总体的一个概率样本，不能当作全体缺考者，也不把其均分直接当作全体均分。',
]


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def build_frame(db, plan):
    """冻结原应考名册。score 原样保存；absent 记录由补测样本提供成绩。"""
    students = db.scalars(select(Student).order_by(Student.code)).all()
    scoped = [s for s in students if plan.campus == '全部' or s.campus == plan.campus]
    return [{
        'id': s.id,
        'code': s.code,
        'name': s.name,
        'campus': s.campus,
        'group': s.group,
        'absent': bool(s.absent),
        # 缺考记为补测框成员，成绩不得当作已观测；非缺考但有成绩者进入已观测总体。
        'missing': bool(s.absent) or s.score is None,
        'score': None if s.absent else s.score,
    } for s in scoped]


def build_strata(frame, per_stratum):
    """按教学点 × 原分组分层。没有缺考者的层保留为空层，π 记为 0。"""
    campuses = sorted({r['campus'] for r in frame})
    strata = []
    for campus in campuses:
        for group in GROUPS:
            codes = sorted(r['code'] for r in frame if r['campus'] == campus and r['group'] == group and r['missing'])
            n = len(codes)
            quota = min(per_stratum, n)
            strata.append({
                'campus': campus,
                'group': group,
                'N': n,
                'quota': quota,
                'pi': quota / n if n else 0.0,
                'empty': n == 0,
                'roster_codes': codes,
            })
    return strata


def create_draw(db, plan_id, per_stratum, actor, seed=None):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, '辅导方案不存在')
    existing = db.scalar(select(SupplementDraw).where(SupplementDraw.plan_id == plan_id))
    if existing:
        # 重试沿用原抽样：同一方案永远只有一份封存的抽样设计。
        return existing
    frame = build_frame(db, plan)
    strata = build_strata(frame, per_stratum)
    seed = seed or secrets.token_hex(16)
    design = {
        'method': '按教学点×原分组分层，从缺考名册无放回随机抽取固定名额；入选概率在抽取前封存。',
        'per_stratum': per_stratum,
        'seed': seed,
        'frame_size': len(frame),
        'frame_sha256': digest(frame),
        'roster': frame,
        'strata': strata,
    }
    draw = SupplementDraw(
        plan_id=plan_id,
        status='pending',
        seed=seed,
        design=design,
        checksum=digest(design),
        created_by=actor,
        created_at=now(),
    )
    db.add(draw)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(SupplementDraw).where(SupplementDraw.plan_id == plan_id))
        if existing:
            return existing
        raise
    db.refresh(draw)
    return draw


def _roster_map(design):
    return {r['code']: r for r in design.get('roster', [])}


def execute_draw(db, draw):
    if draw.status in ('drawn', 'issued'):
        return draw
    design = draw.design
    roster = _roster_map(design)
    rng = random.Random(int(draw.seed, 16))
    createdAt = now()
    # 先以条件更新占据执行权，避免并发/重复点击生成第二份名单。
    claimed = db.execute(update(SupplementDraw)
                         .where(SupplementDraw.id == draw.id, SupplementDraw.status == 'pending')
                         .values(status='drawn')).rowcount
    if not claimed:
        db.rollback()
        db.refresh(draw)
        return draw
    for stratum in design['strata']:
        codes = list(stratum['roster_codes'])
        quota = stratum['quota']
        if quota <= 0:
            continue
        chosen = rng.sample(codes, quota)
        for rank, code in enumerate(chosen, start=1):
            person = roster.get(code)
            if not person:
                continue
            db.add(SupplementSample(
                draw_id=draw.id,
                plan_id=draw.plan_id,
                student_id=person['id'],
                code=person['code'],
                name=person['name'],
                campus=stratum['campus'],
                group=stratum['group'],
                stratum=f"{stratum['campus']}|{stratum['group']}",
                inclusion_probability=stratum['pi'],
                selection_rank=rank,
                outcome='awaiting',
                retest_score=None,
                response_version=0,
                created_at=createdAt,
            ))
    try:
        db.commit()
    except IntegrityError:
        # 唯一约束兜底：另一请求已写入同一批样本，沿用已存在的名单。
        db.rollback()
        if not draw_samples(db, draw.id):
            raise
    db.refresh(draw)
    return draw


def issue_draw(db, draw):
    if draw.status != 'issued':
        # 必须先完成抽取；条件更新避免把待抽取名单误标为已发出。
        changed = db.execute(update(SupplementDraw)
                             .where(SupplementDraw.id == draw.id, SupplementDraw.status == 'drawn')
                             .values(status='issued', issued_at=now())).rowcount
        if not changed:
            db.rollback()
            db.refresh(draw)
            if draw.status == 'pending':
                raise HTTPException(409, '名单尚未抽取，不能发出')
            return draw
        db.commit()
        db.refresh(draw)
    return draw


def list_draws(db, plan_id=None):
    query = select(SupplementDraw).order_by(SupplementDraw.id.desc())
    if plan_id is not None:
        query = query.where(SupplementDraw.plan_id == plan_id)
    return db.scalars(query).all()


def get_draw(db, draw_id):
    draw = db.get(SupplementDraw, draw_id)
    if not draw:
        raise HTTPException(404, '补测抽样不存在')
    return draw


def draw_samples(db, draw_id):
    return db.scalars(select(SupplementSample).where(SupplementSample.draw_id == draw_id).order_by(SupplementSample.id)).all()


def get_sample(db, sample_id):
    sample = db.get(SupplementSample, sample_id)
    if not sample:
        raise HTTPException(404, '补测样本不存在')
    return sample


def register_response(db, sample_id, outcome, retest_score, note, actor, expected_version=None):
    sample = get_sample(db, sample_id)
    draw = db.get(SupplementDraw, sample.draw_id)
    if draw.status != 'issued':
        raise HTTPException(409, '名单尚未发出，暂不能登记回应')
    if outcome not in OUTCOMES or outcome == 'awaiting':
        raise HTTPException(422, '回应只能是 responded、refused 或 unreachable')
    if outcome == 'responded':
        if retest_score is None:
            raise HTTPException(422, '愿意返校补测必须登记 0–100 的补测分')
        if not 0 <= retest_score <= 100:
            raise HTTPException(422, '补测分必须在 0–100 之间')
    else:
        if retest_score is not None:
            raise HTTPException(422, '拒绝或失联不应登记补测分')
    current_version = sample.response_version or 0
    if expected_version is not None and current_version != expected_version:
        raise HTTPException(409, f'该样本回应已被他人更新（当前版本 {current_version}），请刷新后重试')
    responded_at = now()
    # 乐观锁：只有版本仍等于读取值时才能写入，避免并发补分互相覆盖。
    values = {
        'outcome': outcome,
        'retest_score': retest_score if outcome == 'responded' else None,
        'responded_at': responded_at,
        'response_by': actor,
        'response_version': current_version + 1,
    }
    changed = db.execute(update(SupplementSample)
                         .where(SupplementSample.id == sample.id, SupplementSample.response_version == current_version)
                         .values(**values)).rowcount
    if not changed:
        db.rollback()
        db.refresh(sample)
        raise HTTPException(409, f'该样本回应已被他人更新（当前版本 {sample.response_version}），请刷新后重试')
    db.add(SupplementResponse(
        sample_id=sample.id,
        outcome=outcome,
        retest_score=values['retest_score'],
        note=note or '',
        actor=actor,
        created_at=responded_at,
    ))
    db.commit()
    db.refresh(sample)
    return sample


def _group_analysis(group, frame, strata, sample_rows):
    people = [r for r in frame if r['group'] == group]
    observed = [r['score'] for r in people if not r.get('missing') and r['score'] is not None]
    absent = [r for r in people if r.get('missing')]
    target_n = len(observed) + len(absent)
    observed_sum = float(sum(observed))
    absent_n = len(absent)
    by_stratum = {}
    for row in sample_rows:
        if row.group == group:
            by_stratum.setdefault(row.stratum, []).append(row)
    group_strata = []
    known_sum = 0.0
    responded = 0
    awaiting = refused = unreachable = 0
    estimate_available = True
    absent_total_hat = 0.0
    for stratum in strata:
        if stratum['group'] != group:
            continue
        key = f"{stratum['campus']}|{group}"
        rows = by_stratum.get(key, [])
        scores = [r.retest_score for r in rows if r.outcome == 'responded' and r.retest_score is not None]
        responded_h = len(scores)
        known_sum += sum(scores)
        responded += responded_h
        awaiting += sum(1 for r in rows if r.outcome == 'awaiting')
        refused += sum(1 for r in rows if r.outcome == 'refused')
        unreachable += sum(1 for r in rows if r.outcome == 'unreachable')
        if stratum['N'] > 0 and responded_h == 0:
            estimate_available = False
        if stratum['N'] > 0 and responded_h > 0:
            absent_total_hat += stratum['N'] * (sum(scores) / responded_h)
        group_strata.append({
            'campus': stratum['campus'],
            'group': group,
            'N': stratum['N'],
            'quota': stratum['quota'],
            'pi': stratum['pi'],
            'empty': stratum['empty'],
            'sampled': len(rows),
            'responded': responded_h,
            'refused': sum(1 for r in rows if r.outcome == 'refused'),
            'unreachable': sum(1 for r in rows if r.outcome == 'unreachable'),
            'awaiting': sum(1 for r in rows if r.outcome == 'awaiting'),
            'known_sum': sum(scores),
            'response_rate': (responded_h / len(rows)) if rows else None,
            # 每名回应者代表的缺考人数；权重和等于该层缺考总数。
            'expansion_weight': (stratum['N'] / responded_h) if responded_h else None,
        })
    if target_n == 0:
        return {
            'N': 0, 'observed_n': 0, 'observed_sum': 0.0, 'absent_n': 0,
            'sampled_n': 0, 'responded_n': 0, 'unobserved_absent': 0,
            'estimate_available': False, 'mean_estimate': None,
            'mean_low': None, 'mean_high': None, 'naive_mean': None,
            'known_responder_sum': 0.0, 'strata': group_strata,
        }
    unknown_absent = max(0, absent_n - responded)
    mean_low = (observed_sum + known_sum) / target_n
    mean_high = (observed_sum + known_sum + 100.0 * unknown_absent) / target_n
    mean_estimate = None
    if absent_n == 0:
        mean_estimate = observed_sum / target_n
        estimate_available = True
    elif estimate_available:
        mean_estimate = (observed_sum + absent_total_hat) / target_n
    naive_mean = None
    if absent_n == 0:
        naive_mean = observed_sum / target_n
    elif responded > 0:
        responder_mean = known_sum / responded
        naive_mean = (observed_sum + absent_n * responder_mean) / target_n
    return {
        'N': target_n,
        'observed_n': len(observed),
        'observed_sum': observed_sum,
        'absent_n': absent_n,
        'sampled_n': responded + awaiting + refused + unreachable,
        'responded_n': responded,
        'unobserved_absent': unknown_absent,
        'estimate_available': bool(mean_estimate is not None),
        'mean_estimate': mean_estimate,
        'mean_low': mean_low,
        'mean_high': mean_high,
        'naive_mean': naive_mean,
        'known_responder_sum': known_sum,
        'strata': group_strata,
    }


def analyze(draw, sample_rows=None, captured_at=None):
    """生成可封存进报告的补测聚合分析。frame 与 π 均来自冻结设计。"""
    design = draw.design or {}
    frame = design.get('roster', [])
    strata = design.get('strata', [])
    rows = list(sample_rows or [])
    groups = {g: _group_analysis(g, frame, strata, rows) for g in GROUPS}
    ctrl, trt = groups['control'], groups['intervention']
    diff = {'estimate': None, 'low': None, 'high': None, 'identified': False, 'sign_identified': False, 'naive': None}
    if ctrl['N'] and trt['N']:
        diff['low'] = max(-100.0, trt['mean_low'] - ctrl['mean_high'])
        diff['high'] = min(100.0, trt['mean_high'] - ctrl['mean_low'])
        if trt['mean_estimate'] is not None and ctrl['mean_estimate'] is not None:
            diff['estimate'] = trt['mean_estimate'] - ctrl['mean_estimate']
        if trt['naive_mean'] is not None and ctrl['naive_mean'] is not None:
            diff['naive'] = trt['naive_mean'] - ctrl['naive_mean']
        diff['identified'] = ctrl['unobserved_absent'] == 0 and trt['unobserved_absent'] == 0
        diff['sign_identified'] = diff['low'] > 0 or diff['high'] < 0
    sampled = [r for r in rows]
    summary = {
        'sampled': len(sampled),
        'responded': sum(1 for r in sampled if r.outcome == 'responded'),
        'refused': sum(1 for r in sampled if r.outcome == 'refused'),
        'unreachable': sum(1 for r in sampled if r.outcome == 'unreachable'),
        'awaiting': sum(1 for r in sampled if r.outcome == 'awaiting'),
    }
    summary['response_rate'] = (summary['responded'] / summary['sampled']) if summary['sampled'] else None
    warnings = []
    if not diff['identified']:
        warnings.append('仍有未回应或未抽中的缺考者，补测效果无法点识别；组均差以 0–100 分识别区间报告。')
    if summary['refused'] or summary['unreachable']:
        warnings.append('拒绝或失联者未被补抽；不能把愿意返校者的成绩代表全体缺考者。')
    if diff['estimate'] is not None and diff['naive'] is not None and abs(diff['naive'] - diff['estimate']) > 0.01:
        warnings.append('仅用回应者计算的组均差与概率加权估计不同；前者会高估辅导效果。')
    return {
        'draw_id': draw.id,
        'plan_id': draw.plan_id,
        'draw_status': draw.status,
        'checksum': draw.checksum,
        'seed': draw.seed,
        'captured_at': captured_at or now(),
        'frame': {'size': design.get('frame_size'), 'sha256': design.get('frame_sha256')},
        'per_stratum': design.get('per_stratum'),
        'groups': groups,
        'difference': diff,
        'bounds': {'score_range': [0, 100], 'difference_range': [diff['low'], diff['high']]},
        'response_summary': summary,
        'strata': strata,
        'assumptions': ASSUMPTIONS,
        'warnings': warnings,
        'method': '分层补测抽样 + 回应调整概率加权（权重 N_h/r_h = 1/(π_h·r_h/n_h)），聚合冻结应考名册与补测样本估计两组全体均分。',
        'responses': [{
            'sample_id': r.id,
            'code': r.code,
            'name': r.name,
            'campus': r.campus,
            'group': r.group,
            'stratum': r.stratum,
            'inclusion_probability': r.inclusion_probability,
            'outcome': r.outcome,
            'retest_score': r.retest_score,
            'responded_at': r.responded_at,
            'response_version': r.response_version,
        } for r in rows],
    }


def sample_history(db, sample_id):
    """样本去向与依据：冻结名册中的层、入选概率、抽取序号，以及全部回应历史。"""
    sample = get_sample(db, sample_id)
    draw = db.get(SupplementDraw, sample.draw_id)
    design = draw.design or {}
    stratum = next((s for s in design.get('strata', [])
                    if s['campus'] == sample.campus and s['group'] == sample.group), None)
    origin = next((r for r in design.get('roster', []) if r['code'] == sample.code), None)
    responses = db.scalars(select(SupplementResponse).where(SupplementResponse.sample_id == sample.id).order_by(SupplementResponse.id)).all()
    return {
        'sample': {
            'id': sample.id,
            'draw_id': sample.draw_id,
            'code': sample.code,
            'name': sample.name,
            'campus': sample.campus,
            'group': sample.group,
            'stratum': sample.stratum,
            'inclusion_probability': sample.inclusion_probability,
            'selection_rank': sample.selection_rank,
            'outcome': sample.outcome,
            'retest_score': sample.retest_score,
            'responded_at': sample.responded_at,
            'response_by': sample.response_by,
            'response_version': sample.response_version,
        },
        'draw': {
            'id': draw.id,
            'status': draw.status,
            'seed': draw.seed,
            'checksum': draw.checksum,
            'created_at': draw.created_at,
            'issued_at': draw.issued_at,
        },
        'basis': {
            'frame_sha256': design.get('frame_sha256'),
            'frame_size': design.get('frame_size'),
            'stratum': stratum,
            'roster_entry': origin,
            'method': design.get('method'),
        },
        'responses': [{
            'id': r.id,
            'outcome': r.outcome,
            'retest_score': r.retest_score,
            'note': r.note,
            'actor': r.actor,
            'created_at': r.created_at,
        } for r in responses],
    }


def roster_drift(db, draw):
    """抽样后名册修订只作为漂移提示，绝不改写已封存的 π 与入选名单。"""
    design = draw.design or {}
    plan = db.get(Plan, draw.plan_id)
    if not plan:
        return {'changed': True, 'reason': '方案已不存在'}
    current = build_frame(db, plan)
    return {
        'changed': digest(current) != design.get('frame_sha256'),
        'frozen_size': design.get('frame_size'),
        'current_size': len(current),
        'frozen_sha256': design.get('frame_sha256'),
        'current_sha256': digest(current),
        'note': '抽样后修订只影响之后的检验报告快照；本抽样的入选概率与名单保持不变。',
    }


def analysis_for_draw(db, draw):
    if draw.status == 'pending':
        return None
    captured=now()
    return analyze(draw, draw_samples(db, draw.id), captured_at=captured)


def analysis_for_plan(db, plan_id):
    draw = db.scalar(select(SupplementDraw).where(SupplementDraw.plan_id == plan_id))
    if not draw:
        return None
    return analysis_for_draw(db, draw)


def draw_payload(db, draw, include_roster=False):
    design = draw.design or {}
    rows = draw_samples(db, draw.id)
    payload = {
        'id': draw.id,
        'plan_id': draw.plan_id,
        'status': draw.status,
        'seed': draw.seed,
        'checksum': draw.checksum,
        'created_by': draw.created_by,
        'created_at': draw.created_at,
        'issued_at': draw.issued_at,
        'per_stratum': design.get('per_stratum'),
        'frame_size': design.get('frame_size'),
        'frame_sha256': design.get('frame_sha256'),
        'strata': design.get('strata', []),
        'samples': [{
            'id': r.id,
            'student_id': r.student_id,
            'code': r.code,
            'name': r.name,
            'campus': r.campus,
            'group': r.group,
            'stratum': r.stratum,
            'inclusion_probability': r.inclusion_probability,
            'selection_rank': r.selection_rank,
            'outcome': r.outcome,
            'retest_score': r.retest_score,
            'responded_at': r.responded_at,
            'response_by': r.response_by,
            'response_version': r.response_version,
        } for r in rows],
        'analysis': analysis_for_draw(db, draw),
        'roster_drift': roster_drift(db, draw),
    }
    if include_roster:
        payload['roster'] = design.get('roster', [])
        payload['assumptions'] = ASSUMPTIONS
    return payload
