"""CPU targets are independent of the package architecture and desktop profile."""
PROFILES = {
    'x86_64': {'id':'x86_64', 'label':'기존 x86_64 · ISA 등급 미분류',
        'description':'보존한 기존 패키지로 구성합니다. 모든 CPU에서의 실행을 보증하는 등급 표시는 아닙니다.',
        'cflags':[], 'rustflags':[], 'goamd64':'미분류', 'level':'미분류'},
    'x86-64-v3': {'id':'x86-64-v3', 'label':'x86-64-v3 · Intel/AMD 기능 등급',
        'description':'v3 대상 패키지와 CPU 런타임 검증이 확보된 스냅샷에서 활성화됩니다.',
        'cflags':['-march=x86-64-v3','-mtune=generic'], 'rustflags':['-C','target-cpu=x86-64-v3'],
        'goamd64':'v3', 'level':'v3'},
    'x86-64-v4': {'id':'x86-64-v4', 'label':'x86-64-v4 · Intel/AMD 기능 등급',
        'description':'v4 대상 패키지와 CPU 런타임 검증이 확보된 스냅샷에서 활성화됩니다.',
        'cflags':['-march=x86-64-v4','-mtune=generic'], 'rustflags':['-C','target-cpu=x86-64-v4'],
        'goamd64':'v4', 'level':'v4'},
}


def validate_selection(target, binaries):
    if target not in PROFILES:
        raise ValueError('지원되지 않는 CPU 대상입니다.')
    machine = [r for r in binaries if r.get('arch') != 'noarch']
    if not machine or any(r.get('arch') != 'x86_64' for r in machine):
        raise ValueError('x86_64 패키지 구성을 확인하세요.')
    if any(r.get('cpu_profile', 'x86_64') != target for r in machine):
        raise ValueError('선택한 CPU 대상과 패키지 CPU 명세가 다릅니다. 이름만 바꾼 ISO는 생성하지 않습니다.')
    if target != 'x86_64' and any(r.get('cpu_validation') != 'runtime-verified' for r in machine):
        raise ValueError('해당 CPU 대상의 패키지 런타임 검증이 먼저 필요합니다.')
    return PROFILES[target]


def availability(binaries):
    records = list(binaries)
    result = []
    for target, profile in PROFILES.items():
        row = dict(profile)
        try:
            validate_selection(target, records)
            row.update(available=True, reason='ISO 구성 가능' if target == 'x86_64' else 'CPU 대상 런타임 검증 명세 확인')
        except ValueError as error:
            row.update(available=False, reason=str(error))
        result.append(row)
    return result
