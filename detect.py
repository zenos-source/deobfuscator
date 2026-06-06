import re

def detect_obfuscator(content):
    content_lower = content.lower()
    results = {
        'obfuscator': 'unknown',
        'confidence': 0,
        'details': []
    }
    
    checks = {
        'luraph': [(r'luraph', 90), (r'vmp', 60)],
        'moonsec': [(r'moonsec', 95), (r'moon[-_]?sec', 90)],
        'ironbrew': [(r'ironbrew', 95), (r'ib2?', 70)],
        'prometheus': [(r'prometheus', 95)],
        'psu': [(r'psu[-\s]?v?\d+', 90)],
        'luarmor': [(r'luarmor', 95)],
    }
    
    for obf, patterns in checks.items():
        for pattern, confidence in patterns:
            if re.search(pattern, content_lower):
                if confidence > results['confidence']:
                    results['obfuscator'] = obf
                    results['confidence'] = confidence
    
    return results
