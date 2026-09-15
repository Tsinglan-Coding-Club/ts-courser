"""Canonical quiz parsing and student-facing data boundaries."""

import json
import re
import unicodedata

from django.utils.crypto import salted_hmac


def token_id(episode, question_index, original_id):
    """An opaque identifier that reveals neither a token's line nor position."""
    value = json.dumps([episode.pk, episode.info_page_content, question_index, original_id])
    return salted_hmac('quiz-token', value, algorithm='sha256').hexdigest()


def student_questions(episode, *, released=False):
    questions = _parse_quiz_markdown(episode.info_page_content or '')
    if released:
        return questions
    public = []
    for index, question in enumerate(questions):
        item = {'type': question['type'], 'question': question['question']}
        if question['type'] != 'cba':
            item['choices'] = [{'text': c['text']} for c in question['choices']]
        else:
            item['language'] = question['language']
            choices = {}
            for choice in question['choices']:
                choices[choice['id']] = {
                    key: choice[key] for key in (
                        'text', 'kind', 'hint', 'leadingIndent', 'displayText'
                    ) if key in choice
                }
                choices[choice['id']]['id'] = token_id(episode, index, choice['id'])
            # Sorting by opaque IDs removes the original correct token order.
            item['choices'] = sorted(choices.values(), key=lambda c: c['id'])
            item['lines'] = [
                {'choices': [
                    choices[c['id']] if c.get('hint') else {'hint': False, 'kind': 'slot'}
                    for c in line['choices']
                ]}
                for line in question['lines']
            ]
        public.append(item)
    return public


def validate_answers(episode, answers):
    """Validate untrusted answers and return canonical data for storage/review."""
    questions = _parse_quiz_markdown(episode.info_page_content or '')
    if not questions:
        raise ValueError('This quiz has no questions.')
    if not isinstance(answers, dict) or not isinstance(answers.get('questions'), list):
        raise ValueError('Invalid answers format.')
    if len(answers['questions']) != len(questions):
        raise ValueError('Answer count does not match quiz.')
    normalized = []
    for index, (question, answer) in enumerate(zip(questions, answers['questions'])):
        label = f'Question {index + 1}'
        kind = question['type']
        if not isinstance(answer, dict) or answer.get('type') != kind:
            raise ValueError(f'{label}: invalid answer type.')
        entry = {'type': kind}
        count = len(question['choices'])
        if kind == 'mcq':
            selected = answer.get('selectedIndex')
            if selected is not None and (type(selected) is not int or not 0 <= selected < count):
                raise ValueError(f'{label}: invalid choice.')
            complete = selected is not None
            if complete:
                entry['selectedIndex'] = selected
        elif kind in ('mrq', 'srt'):
            selected = answer.get('selectedIds', [])
            if (
                not isinstance(selected, list)
                or any(type(i) is not int or not 0 <= i < count for i in selected)
                or len(selected) != len(set(selected))
            ):
                raise ValueError(f'{label}: invalid choices.')
            complete = len(selected) == count if kind == 'srt' else bool(selected)
            entry['selectedIds'] = selected
        elif kind == 'frq':
            value = answer.get('text', '')
            if not isinstance(value, str) or len(value) > 20000:
                raise ValueError(f'{label}: invalid text answer (maximum 20000 characters).')
            complete = bool(value.strip())
            entry['text'] = value
        elif kind == 'cba':
            lines = answer.get('tokenIds')
            if not isinstance(lines, list) or len(lines) != len(question['lines']):
                raise ValueError(f'{label}: invalid code assembly lines.')
            allowed = {
                token_id(episode, index, c['id']): c['id']
                for c in question['choices'] if not c.get('hint')
            }
            seen = set()
            canonical_lines = []
            for line, expected in zip(lines, question['lines']):
                capacity = sum(not c.get('hint') for c in expected['choices'])
                if not isinstance(line, list) or len(line) > capacity:
                    raise ValueError(f'{label}: too many tokens on a line.')
                converted = []
                for submitted_id in line:
                    if not isinstance(submitted_id, str) or submitted_id not in allowed or submitted_id in seen:
                        raise ValueError(f'{label}: invalid or repeated token.')
                    seen.add(submitted_id)
                    converted.append(allowed[submitted_id])
                canonical_lines.append(converted)
            complete = len(seen) == len(allowed)
            entry['tokenIds'] = canonical_lines
        else:
            raise ValueError(f'{label}: unsupported question type.')
        if episode.quiz_require_all and not complete:
            raise ValueError(f'{label}: an answer is required.')
        normalized.append(entry)
    return {'questions': normalized}


def review_answers(episode, raw):
    """Render historical submissions safely, treating invalid fields as unanswered."""
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        stored = None
    answers = stored.get('questions') if isinstance(stored, dict) else None
    if not isinstance(answers, list):
        answers = []
    cleaned = []
    for index, question in enumerate(_parse_quiz_markdown(episode.info_page_content or '')):
        answer = answers[index] if index < len(answers) and isinstance(answers[index], dict) else {}
        kind = question['type']
        result = {'type': kind}
        count = len(question['choices'])
        if kind == 'mcq':
            selected = answer.get('selectedIndex')
            if type(selected) is int and 0 <= selected < count:
                result['selectedIndex'] = selected
        elif kind in ('mrq', 'srt'):
            ids = answer.get('selectedIds')
            result['selectedIds'] = list(dict.fromkeys(
                i for i in ids if type(i) is int and 0 <= i < count
            )) if isinstance(ids, list) else []
        elif kind == 'frq':
            result['text'] = answer.get('text') if isinstance(answer.get('text'), str) else ''
        elif kind == 'cba':
            source = answer.get('tokenIds')
            allowed = {c['id'] for c in question['choices'] if not c.get('hint')}
            seen = set()
            result['tokenIds'] = []
            for line_index, expected in enumerate(question['lines']):
                line = source[line_index] if isinstance(source, list) and line_index < len(source) else []
                capacity = sum(not c.get('hint') for c in expected['choices'])
                valid = []
                if isinstance(line, list):
                    for value in line:
                        if isinstance(value, str) and value in allowed and value not in seen and len(valid) < capacity:
                            valid.append(value)
                            seen.add(value)
                result['tokenIds'].append(valid)
        cleaned.append(result)
    return {'questions': cleaned}


def _parse_quiz_markdown(md):
    """Parse quiz markdown into structured question objects (mirrors JS parser)."""
    import re
    if not md or not md.strip():
        return []

    blocks = _split_quiz_blocks(md)
    questions = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n')

        cba_question = _parse_cba_block(lines)
        if cba_question is not None:
            questions.append(cba_question)
            continue

        first_choice = -1
        for j, line in enumerate(lines):
            if re.match(r'^>', line):
                first_choice = j
                break

        if first_choice == -1:
            question_text = '\n'.join(lines).strip()
            choice_lines = []
        else:
            question_text = '\n'.join(lines[:first_choice]).strip()
            choice_lines = lines[first_choice:]

        if not question_text:
            continue

        # Skip "None" (Django null artifact, mirrors JS parser)
        if question_text == 'None':
            continue

        choices = []
        has_mrq = False
        has_sort = False
        has_correct = False

        for line in choice_lines:
            m_frq_ref = re.match(r'^>= (.+)$', line)
            m_frq_e = re.match(r'^>=\s*$', line)
            m_mcq = re.match(r'^>\+ (.+)$', line)
            m_mcq_e = re.match(r'^>\+\s*$', line)
            m_mrq = re.match(r'^>\* (.+)$', line)
            m_mrq_e = re.match(r'^>\*\s*$', line)
            m_sort = re.match(r'^>(\d+)(?:\s+(.+))?$', line)
            m_wrong = re.match(r'^> (?!\+)(?!\*)(.+)$', line)
            m_empty = re.match(r'^>\s*$', line)

            if m_frq_ref:
                choices.append({'text': m_frq_ref.group(1).strip(), 'isCorrect': False, 'isFRQRef': True})
            elif m_frq_e:
                choices.append({'text': '', 'isCorrect': False, 'isFRQRef': True})
            elif m_mcq:
                choices.append({'text': m_mcq.group(1).strip(), 'isCorrect': True})
                has_correct = True
            elif m_mcq_e:
                choices.append({'text': '', 'isCorrect': True})
                has_correct = True
            elif m_mrq:
                choices.append({'text': m_mrq.group(1).strip(), 'isCorrect': True})
                has_mrq = True
                has_correct = True
            elif m_mrq_e:
                choices.append({'text': '', 'isCorrect': True})
                has_mrq = True
                has_correct = True
            elif m_sort:
                choices.append({
                    'text': m_sort.group(2).strip() if m_sort.group(2) else '',
                    'isCorrect': False,
                    'sortPosition': int(m_sort.group(1))
                })
                has_sort = True
            elif m_wrong:
                choices.append({'text': m_wrong.group(1).strip(), 'isCorrect': False})
            elif m_empty:
                choices.append({'text': '', 'isCorrect': False})

        is_frq = (len(choices) == 0
                  or (len(choices) == 1 and choices[0]['text'] == '')
                  or (len(choices) == 1 and choices[0].get('isFRQRef')))

        # Auto-mark first choice as correct if none marked and choices exist
        if not is_frq and not has_correct and len(choices) > 0:
            choices[0]['isCorrect'] = True

        ref_answer = ''
        if is_frq and len(choices) == 1 and choices[0].get('isFRQRef'):
            ref_answer = choices[0]['text']
        if is_frq:
            qtype = 'frq'
        elif has_sort:
            qtype = 'srt'
        elif has_mrq:
            qtype = 'mrq'
        else:
            qtype = 'mcq'

        questions.append({
            'type': qtype,
            'question': question_text,
            'choices': [] if is_frq else choices,
            'refAnswer': ref_answer,
        })

    return questions


def _fence_marker(line):
    """Return a Markdown fence marker, ignoring indentation of up to 3 spaces."""
    match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
    if not match:
        return None
    marker = match.group(1)
    return marker[0], len(marker), match.group(2).strip()


def _split_quiz_blocks(md):
    """Split on level-two quiz headings, except while inside fenced code."""
    blocks = []
    current = []
    open_fence = None

    for line in md.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        marker = _fence_marker(line)
        if open_fence:
            current.append(line)
            if (
                marker
                and marker[0] == open_fence[0]
                and marker[1] >= open_fence[1]
                and not marker[2]
            ):
                open_fence = None
            continue

        if marker:
            open_fence = (marker[0], marker[1])
            current.append(line)
        elif re.match(r'^## (?![#])', line):
            if current:
                blocks.append('\n'.join(current))
            current = [line[3:]]
        else:
            current.append(line)

    if current:
        blocks.append('\n'.join(current))
    return blocks


def _generic_cba_cuts(text):
    """Create stable code-point cuts for code without usable editor metadata."""
    if not text:
        return []

    operators = (
        '>>=', '<<=', '**=', '//=', '...', '===', '!==', '=>', '==', '!=',
        '<=', '>=', '<<', '>>', '**', '//', '+=', '-=', '*=', '/=', '%=',
        '&=', '|=', '^=', '->', ':=', '&&', '||', '??', '?.', '++', '--',
        '(', ')', '[', ']', '{', '}', ',', ':', ';', '.', '+', '-', '*', '/',
        '%', '<', '>', '=', '!', '&', '|', '^', '~', '?', '@', '\\',
    )

    def is_identifier_start(character):
        return (
            character in '_$'
            or 'A' <= character <= 'Z'
            or 'a' <= character <= 'z'
            or unicodedata.category(character).startswith('L')
        )

    def is_identifier_part(character):
        return is_identifier_start(character) or '0' <= character <= '9'

    cuts = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if (
            character == '#'
            or text.startswith('//', index)
            or text.startswith('--', index)
        ):
            cuts.append(length)
            break

        quote_index = index
        if (
            quote_index + 2 < length
            and text[quote_index] in 'fFrRbBuU'
            and text[quote_index + 1] in 'fFrRbBuU'
            and text[quote_index + 2] in "'\""
        ):
            quote_index += 2
        elif (
            quote_index + 1 < length
            and text[quote_index] in 'fFrRbBuU'
            and text[quote_index + 1] in "'\""
        ):
            quote_index += 1
        if text[quote_index] in "'\"":
            quote = text[quote_index]
            index = quote_index + 1
            while index < length:
                if text[index] == '\\':
                    index = min(index + 2, length)
                    continue
                if text[index] == quote:
                    index += 1
                    break
                index += 1
            cuts.append(index)
            continue

        if is_identifier_start(character):
            index += 1
            while index < length and is_identifier_part(text[index]):
                index += 1
            cuts.append(index)
            continue

        if character.isascii() and character.isdigit() or (
            character == '.'
            and index + 1 < length
            and text[index + 1].isascii()
            and text[index + 1].isdigit()
        ):
            index += 1
            while index < length and (
                text[index].isascii()
                and (text[index].isalnum() or text[index] in '_.')
            ):
                index += 1
            cuts.append(index)
            continue

        operator = next(
            (candidate for candidate in operators if text.startswith(candidate, index)),
            None,
        )
        index += len(operator) if operator else 1
        cuts.append(index)

    if not cuts or cuts[-1] != length:
        cuts.append(length)
    return cuts


def _valid_cba_config(config, language, code_lines):
    if (
        not isinstance(config, dict)
        or type(config.get('v')) is not int
        or config.get('v') != 1
        or config.get('language') != language
        or config.get('indentation') not in ('visible', 'sortable')
        or not isinstance(config.get('lines'), list)
        or len(config['lines']) != len(code_lines)
    ):
        return False

    for source_line, line_config in zip(code_lines, config['lines']):
        body = source_line.lstrip(' \t')
        if not isinstance(line_config, dict):
            return False
        if (
            'indentMerged' in line_config
            and type(line_config['indentMerged']) is not bool
        ):
            return False
        if (
            'indentHint' in line_config
            and type(line_config['indentHint']) is not bool
        ):
            return False
        cuts = line_config.get('cuts')
        hints = line_config.get('hints')
        if not isinstance(cuts, list) or not isinstance(hints, list):
            return False
        if len(cuts) != len(hints) or not all(type(hint) is bool for hint in hints):
            return False
        if any(type(cut) is not int for cut in cuts):
            return False
        if cuts != sorted(set(cuts)) or any(cut <= 0 for cut in cuts):
            return False
        if (cuts and cuts[-1] != len(body)) or (not cuts and body):
            return False
    return True


def _parse_cba_block(lines):
    """Parse the two-fence CBA representation from one quiz question block."""
    fences = []
    index = 0
    while index < len(lines):
        marker = _fence_marker(lines[index])
        if not marker or not marker[2]:
            index += 1
            continue
        fence_type, fence_length, info = marker
        content = []
        end_index = index + 1
        while end_index < len(lines):
            closing = _fence_marker(lines[end_index])
            if (
                closing
                and closing[0] == fence_type
                and closing[1] >= fence_length
                and not closing[2]
            ):
                break
            content.append(lines[end_index])
            end_index += 1
        if end_index >= len(lines):
            return None
        fences.append((info, content, index, end_index))
        index = end_index + 1

    code_fence = next(
        (
            fence for fence in fences
            if fence[0] and fence[0].split()[0] == 'quiz-cba'
        ),
        None,
    )
    config_fence = next(
        (fence for fence in fences if fence[0] == 'quiz-cba-config'),
        None,
    )
    if not code_fence:
        return None

    info_parts = code_fence[0].split(maxsplit=1)
    language = info_parts[1].strip() if len(info_parts) == 2 else 'python'
    code_lines = code_fence[1]
    code = '\n'.join(code_lines)

    config = None
    if config_fence:
        try:
            config = json.loads('\n'.join(config_fence[1]))
        except (json.JSONDecodeError, TypeError):
            config = None

    config_valid = _valid_cba_config(config, language, code_lines)
    indentation = config['indentation'] if config_valid else 'visible'
    if config_valid:
        config_lines = config['lines']
    else:
        config_lines = []
        for line in code_lines:
            cuts = _generic_cba_cuts(line.lstrip(' \t'))
            config_lines.append({
                'cuts': cuts,
                'hints': [False] * len(cuts),
                'indentMerged': False,
            })

    excluded_line_indexes = set()
    for fence in (code_fence, config_fence):
        if fence:
            excluded_line_indexes.update(range(fence[2], fence[3] + 1))
    question = '\n'.join(
        line for line_index, line in enumerate(lines)
        if line_index not in excluded_line_indexes
    ).strip()
    if not question or question == 'None':
        return None

    choices = []
    parsed_lines = []
    for line_index, (source_line, line_config) in enumerate(
        zip(code_lines, config_lines)
    ):
        leading = source_line[:len(source_line) - len(source_line.lstrip(' \t'))]
        body = source_line[len(leading):]
        choice_ids = []
        indent_merged = bool(
            line_config.get('indentMerged')
            and leading
            and line_config['cuts']
        )
        indent_hint = line_config.get(
            'indentHint', indentation == 'visible'
        )

        if leading and not indent_merged:
            indent_choice = {
                'id': f'l{line_index}i',
                'text': leading,
                'line': line_index,
                'kind': 'indent',
                'hint': indent_hint,
                'displayText': leading.replace('\t', '⇥').replace(' ', '·'),
            }
            choices.append(indent_choice)
            choice_ids.append(indent_choice['id'])

        start = 0
        cuts = line_config['cuts']
        hints = line_config['hints']
        for chunk_index, end in enumerate(cuts):
            chunk_text = body[start:end]
            chunk_hint = hints[chunk_index]
            if chunk_index == 0 and indent_merged:
                chunk_text = leading + chunk_text
                chunk_hint = chunk_hint or indent_hint
            chunk_choice = {
                'id': f'l{line_index}c{chunk_index}',
                'text': chunk_text,
                'line': line_index,
                'kind': 'token',
                'hint': chunk_hint,
                'leadingIndent': leading if chunk_index == 0 and indent_merged else '',
            }
            choices.append(chunk_choice)
            choice_ids.append(chunk_choice['id'])
            start = end

        parsed_lines.append({
            'index': line_index,
            'raw': source_line,
            'indent': leading,
            'indentMerged': indent_merged,
            'indentHint': indent_hint,
            'choices': [
                choice for choice in choices if choice['line'] == line_index
            ],
            'choiceIds': choice_ids,
        })

    return {
        'type': 'cba',
        'question': question,
        'language': language,
        'code': code,
        'indentation': indentation,
        'choices': choices,
        'lines': parsed_lines,
    }
