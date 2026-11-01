#!/usr/bin/env python3
"""Check original Startup bytes governing external slot-3 initialization."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    code = ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin'
    monitor = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    assert sha(code) == '6ab2fbcabf775881e948d7d343e6fd6e5908253fcb939cc87bc3b76a0fa87956'
    assert sha(monitor) == 'c92e4db8d40298b759d756a23e51e8d99086cb625e4fbe8074c8c9b2a6bad554'
    data = code.read_bytes()
    checks = {
        0x02CA: '0c47000367000190',
        0x0456: '48c72f074eba4840584f',
        0x04AC: '2f3c0000c000487840004eba401a',
        0x44D2: '4e560000302e000a322e000e6106',
        0x44E6: '226dedca4a2900083340001c08e90003000d534142290010137c00ea0010534151c9fff24e75',
        0x4CEE: '3003e1480640c000323c01006100f7ea',
    }
    for offset, expected in checks.items():
        assert data[offset:offset + len(expected) // 2].hex() == expected, hex(offset)
    firmware = monitor.read_bytes()
    assert firmware[0x305:0x308] == firmware[0x3C9C:0x3C9F] == bytes.fromhex('389018')
    assert firmware[0x38B7:0x38CF].hex() == '8d06c0a202bd05c3dd9cfcd007caca10f488d0ef8d07c060'
    initial_fill = bytes.fromhex('00ea') * (0xC000 // 2)
    slot3 = initial_fill[0xC300 - 0x4000:0xC400 - 0x4000]
    assert len(slot3) == 256 and slot3[7] == 0xEA
    result = {
        'scope': 'static original-byte checks; no Macintosh or 65C02 execution',
        'code1_windows': {f'{offset:04X}': value for offset, value in checks.items()},
        'host_initial_fill': {'start': '4000', 'count': 0xC000, 'pattern': '00EA',
                              'sha256': hashlib.sha256(initial_fill).hexdigest()},
        'external_slot3_snapshot': {'host_start': 'C300', 'count': 256,
                                    'sha256': hashlib.sha256(slot3).hexdigest(),
                                    'C307': 'EA', 'comparison_FC9E': '18'},
        'inputs_sha256': {str(path): sha(path) for path in (code, monitor, Path(__file__))},
    }
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS original slot3 fill and upload exclusion bytes')


if __name__ == '__main__':
    main()
