"""
long_maker — превращает учебный план .plx в long.csv.

Каждая строка результата = дисциплина в конкретном (абсолютном) семестре.
Логика перенесена из ноутбуков пайплайна (PLX → ... → long.csv) и собрана
в один модуль без промежуточных XML/JSON файлов.
"""

import csv
import io
import xml.etree.ElementTree as ET
from collections import defaultdict


# ── Утилиты ────────────────────────────────────────────────────────────────

def clean_tag_name(tag):
    """Удаляет namespace из XML тега."""
    pos = tag.rfind('}')
    return tag[pos + 1:] if pos > -1 else tag


def get_competency_type(type_code):
    """Определяет тип компетенции по коду."""
    type_map = {2: "УК", 3: "ОПК", 4: "ПК"}
    return type_map.get(int(type_code) if type_code else 0, "Не указан")


# ── Разбор .plx ────────────────────────────────────────────────────────────

def build_references(root):
    """Извлекает справочники видов работ, типов и видов объектов."""
    refs = {'work_kinds': {}, 'obj_types': {}, 'obj_kinds': {}}

    for elem in root.iter():
        tag = clean_tag_name(elem.tag)
        attr = elem.attrib

        if tag == "СправочникВидыРабот":
            refs['work_kinds'][attr.get("Код")] = attr.get("Название")
        elif tag == "СправочникТипОбъекта":
            refs['obj_types'][attr.get("Код")] = attr.get("Название")
        elif tag == "СправочникВидОбъекта":
            refs['obj_kinds'][attr.get("Код")] = attr.get("Наименование")

    return refs


def extract_program_metadata(root):
    """Извлекает направление и профили (нужно для распределения дисциплин по ООП)."""
    direction = {}
    profiles = []

    for elem in root.iter():
        if clean_tag_name(elem.tag) == "ООП":
            attr = elem.attrib
            if not attr.get('КодРодительскогоООП'):
                direction = {
                    'id': attr.get('Код'),
                    'name': attr.get('Название'),
                    'code': attr.get('Шифр'),
                }
            else:
                profiles.append({'id': attr.get('Код'), 'name': attr.get('Название')})

    # Если профилей нет, создаем фиктивный = направлению
    if not profiles and direction:
        profiles = [{'id': direction['id'], 'name': direction['name']}]

    return direction, profiles


def extract_competencies(root):
    """Справочник компетенций/индикаторов для связи с дисциплинами."""
    comp_lookup = {}  # {comp_id: {'code', 'title', 'category'}}

    for elem in root.iter():
        if clean_tag_name(elem.tag) == 'ПланыКомпетенции':
            attr = elem.attrib
            comp_lookup[attr.get('Код')] = {
                'code': attr.get("ШифрКомпетенции", ""),
                'title': attr.get("Наименование"),
                'category': attr.get('Категория'),
            }

    return comp_lookup


def extract_disciplines(root, refs, comp_lookup, direction_id):
    """Извлекает дисциплины с распределением часов и связанными компетенциями."""
    control_forms_codes = {'1', '2', '3', '4', '5', '6', '49'}

    # Связи дисциплина -> компетенции
    disc_to_comp = {}
    for elem in root.iter():
        if clean_tag_name(elem.tag) == 'ПланыКомпетенцииДисциплины':
            line_id = elem.attrib.get('КодСтроки')
            comp_id = elem.attrib.get('КодКомпетенции')
            disc_to_comp.setdefault(line_id, [])
            if comp_id in comp_lookup:
                disc_to_comp[line_id].append(comp_lookup[comp_id])

    # Часы по семестрам
    hours_data = {}
    for elem in root.iter():
        if clean_tag_name(elem.tag) == 'ПланыНовыеЧасы':
            attr = elem.attrib
            obj_id = attr.get('КодОбъекта')
            work_code = attr.get('КодВидаРаботы')
            hours_data.setdefault(obj_id, {'hours': [], 'control': {}})
            work_name = refs['work_kinds'].get(work_code, f"Код {work_code}")
            hours_data[obj_id]['hours'].append({
                'course': attr.get('Курс'),
                'semester': attr.get('Семестр'),
                'work_type': work_name,
                'hours': attr.get('Количество'),
            })
            if work_code in control_forms_codes:
                sem_key = f"{attr.get('Курс')}.{attr.get('Семестр')}"
                hours_data[obj_id]['control'].setdefault(sem_key, []).append(work_name)

    # Собираем дисциплины
    disciplines_by_oop = {'common': []}
    for elem in root.iter():
        if clean_tag_name(elem.tag) == "ПланыСтроки":
            attr = elem.attrib
            obj_id = attr.get('Код')
            oop_id = attr.get('КодООП')
            hours_info = hours_data.get(obj_id, {'hours': [], 'control': {}})

            discipline = {
                'id': obj_id,
                'code': attr.get('ДисциплинаКод'),
                'name': attr.get('Дисциплина'),
                'type': refs['obj_types'].get(attr.get('ТипОбъекта')),
                'kind': refs['obj_kinds'].get(attr.get('ВидОбъекта')),
                'credits': attr.get('ЗЕТфакт'),
                'total_hours': attr.get('ЧасовПоПлану'),
                'hours_distribution': hours_info['hours'],
                'control_forms': hours_info['control'],
                'competencies': disc_to_comp.get(obj_id, []),
            }

            is_common = not oop_id or oop_id == '0' or oop_id == direction_id
            if is_common:
                disciplines_by_oop['common'].append(discipline)
            else:
                disciplines_by_oop.setdefault(oop_id, []).append(discipline)

    return disciplines_by_oop


# ── Сборка long-формата ────────────────────────────────────────────────────

LONG_FIELDNAMES = [
    'discipline_code', 'discipline', 'exam', 'pass', 'graded_pass', 'credits',
    'lectures', 'labs', 'practice', 'solo', 'control', 'competences',
    'semester', 'grade_year', 'no_skip', 'praxis',
]


def build_long_rows(disciplines):
    """Из списка дисциплин строит строки long-формата (по одной на семестр)."""
    long_list = []

    for disc in disciplines:
        disc_code = disc.get('code', '') or ''
        disc_name = disc.get('name', '') or ''
        disc_type = disc.get('type', '')

        # Пропускаем "Блоки по выбору"
        if disc_type == 'Блоки по выбору':
            continue

        # Строка компетенций
        competences_str = '; '.join([c.get('code', '') for c in disc.get('competencies', [])])

        # no_skip: для дисциплин по выбору учитываем только первый вариант (.01)
        if '.ДВ.' in disc_code and disc_code.count('.') == 2:
            no_skip = 0
        elif '.ДВ.' in disc_code and disc_code.count('.') == 3:
            no_skip = 1 if disc_code.split('.')[-1] == '01' else 0
        else:
            no_skip = 1

        # Тип практики
        if '(У)' in disc_code:
            praxis = 'У'
        elif '(П)' in disc_code:
            praxis = 'П'
        else:
            praxis = '0'

        # Группируем часы по абсолютным семестрам
        semesters_data = defaultdict(lambda: {
            'credits': '', 'lectures': '', 'labs': '', 'practice': '',
            'solo': '', 'control': '', 'exam': 0, 'pass': 0, 'graded_pass': 0,
        })

        for item in disc.get('hours_distribution', []):
            course = item.get('course', '')
            semester_in_year = item.get('semester', '')
            work_type = item.get('work_type', '')
            hours = item.get('hours', '')
            if not course or not semester_in_year:
                continue

            absolute_semester = (int(course) - 1) * 2 + int(semester_in_year)
            sd = semesters_data[absolute_semester]

            if work_type == 'ЗЕТ':
                sd['credits'] = hours
            elif work_type == 'Лекционные занятия':
                sd['lectures'] = hours
            elif work_type == 'Лабораторные занятия':
                sd['labs'] = hours
            elif work_type == 'Практические занятия':
                sd['practice'] = hours
            elif work_type == 'Самостоятельная работа':
                sd['solo'] = hours
            elif work_type == 'Контроль':
                sd['control'] = hours
            elif work_type == 'Экзамен':
                sd['exam'] = 1
            elif work_type == 'Зачет':
                sd['pass'] = 1
            elif work_type == 'Зачет с оценкой':
                sd['graded_pass'] = 1

        # Запись на каждый семестр с данными
        for semester, sd in sorted(semesters_data.items()):
            long_list.append({
                'discipline_code': disc_code,
                'discipline': disc_name,
                'exam': sd['exam'],
                'pass': sd['pass'],
                'graded_pass': sd['graded_pass'],
                'credits': sd['credits'],
                'lectures': sd['lectures'],
                'labs': sd['labs'],
                'practice': sd['practice'],
                'solo': sd['solo'],
                'control': sd['control'],
                'competences': competences_str,
                'semester': semester,
                'grade_year': (semester + 1) // 2,
                'no_skip': no_skip,
                'praxis': praxis,
            })

    long_list.sort(key=lambda x: (x['semester'], x['discipline_code']))
    return long_list


# ── Высокоуровневый API ────────────────────────────────────────────────────

def plx_to_long(plx_source, profile_index=0):
    """Разбирает .plx и возвращает (info, rows).

    plx_source: путь к файлу, bytes или file-like объект с XML.
    profile_index: какой профиль брать, если их несколько.

    info: dict с метаданными (direction, program_name, profiles, ...).
    rows: список dict-строк long-формата.
    """
    if isinstance(plx_source, (bytes, bytearray)):
        root = ET.fromstring(plx_source)
    elif hasattr(plx_source, 'read'):
        root = ET.parse(plx_source).getroot()
    else:
        root = ET.parse(plx_source).getroot()

    references = build_references(root)
    direction, profiles = extract_program_metadata(root)
    comp_lookup = extract_competencies(root)
    disciplines_by_oop = extract_disciplines(root, references, comp_lookup, direction.get('id'))

    if not profiles:
        profiles = [{'id': None, 'name': direction.get('name', '')}]
    profile_index = max(0, min(profile_index, len(profiles) - 1))
    profile = profiles[profile_index]

    disciplines = disciplines_by_oop.get('common', []) + disciplines_by_oop.get(profile['id'], [])
    rows = build_long_rows(disciplines)

    info = {
        'direction_code': direction.get('code', ''),
        'direction_name': direction.get('name', ''),
        'direction': f"{direction.get('code', '')} {direction.get('name', '')}".strip(),
        'program_name': profile['name'],
        'profiles': [p['name'] for p in profiles],
        'profile_index': profile_index,
        'discipline_count': len(disciplines),
        'row_count': len(rows),
    }
    return info, rows


def rows_to_csv(rows):
    """Сериализует строки long-формата в CSV-строку (как в эталонном long.csv)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LONG_FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
