"""Validation for browser-reported code execution feedback."""


def validate_test_results(value):
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError('Test results must be a list of at most 200 results.')
    normalized = []
    for item in value:
        if not isinstance(item, dict) or type(item.get('passed')) is not bool:
            raise ValueError('Each test result must contain a boolean passed field.')
        result = {'passed': item['passed']}
        for key in ('input', 'expected', 'actual', 'error'):
            field = item.get(key, '')
            if not isinstance(field, str) or len(field) > 100000:
                raise ValueError(f'Invalid {key} in test results.')
            result[key] = field
        normalized.append(result)
    return normalized
