import csv
import gzip

MISSING_TOKENS = {'.', 'NA', 'N/A', 'NULL', 'NaN', 'nan'}

def _is_missing(value):
    if value is None:
        return True
    value = value.strip()
    return value == '' or value in MISSING_TOKENS

def _clean(value):
    if value is None:
        return ''
    value = value.strip()
    if value == '' or value in MISSING_TOKENS:
        return ''
    return value

def _usable_allele(value):
    if not value:
        return False
    return all(ch in 'ACGTacgt' for ch in value)

def _open_input(path):
    with open(path, 'rb') as f:
        magic = f.read(2)
    if magic == bytes([0x1f, 0x8b]):
        return gzip.open(path, 'rt', encoding='utf-8', newline='')
    return open(path, 'r', encoding='utf-8', newline='')

def transform(input_path, output_path, context):
    context = context or {}
    delimiter = context.get('input_delimiter', chr(9))
    if delimiter is None or delimiter == 'whitespace':
        delimiter = chr(9)

    canonical_header = [
        'SNP', 'CHR', 'BP', 'effect_allele', 'other_allele', 'beta', 'or', 'se',
        'z', 'pval', 'neglog10_pval', 'freq_qc', 'info', 'n', 'n_cases', 'n_controls'
    ]

    source_fields = [
        'p_value', 'chromosome', 'base_pair_location', 'effect_allele', 'other_allele',
        'effect_allele_frequency', 'odds_ratio', 'beta', 'standard_error', 'cases', 'n'
    ]

    with _open_input(input_path) as fin, open(output_path, 'w', encoding='utf-8', newline='') as fout:
        reader = csv.reader(fin, delimiter=delimiter)
        try:
            raw_header = next(reader)
        except StopIteration:
            raise RuntimeError('Input file is empty')

        header = []
        for h in raw_header:
            h = h.strip()
            if h and h[0] == chr(0xFEFF):
                h = h[1:].strip()
            header.append(h)

        index = {name: i for i, name in enumerate(header)}

        missing_cols = [name for name in source_fields if name not in index]
        if missing_cols:
            raise RuntimeError('Missing required source columns: ' + ', '.join(missing_cols))

        def field(row, name):
            i = index.get(name)
            if i is None or i >= len(row):
                return ''
            return row[i]

        writer = csv.writer(fout, delimiter=chr(9), lineterminator=chr(10), quoting=csv.QUOTE_MINIMAL)
        writer.writerow(canonical_header)

        rows_written = 0
        preview_rows = []
        preview_limit = 5

        for row in reader:
            if not row:
                continue
            if all(_is_missing(cell) for cell in row):
                continue

            p_value = _clean(field(row, 'p_value'))
            chromosome = _clean(field(row, 'chromosome'))
            bp = _clean(field(row, 'base_pair_location'))
            effect_raw = _clean(field(row, 'effect_allele'))
            other_raw = _clean(field(row, 'other_allele'))
            freq = _clean(field(row, 'effect_allele_frequency'))
            odds_ratio = _clean(field(row, 'odds_ratio'))
            beta = _clean(field(row, 'beta'))
            se = _clean(field(row, 'standard_error'))
            cases = _clean(field(row, 'cases'))
            n = _clean(field(row, 'n'))

            if _usable_allele(effect_raw) and _usable_allele(other_raw):
                effect_allele = effect_raw
                other_allele = other_raw
            else:
                effect_allele = ''
                other_allele = ''

            output_row = [
                '',
                chromosome,
                bp,
                effect_allele,
                other_allele,
                beta,
                odds_ratio,
                se,
                '',
                p_value,
                '',
                freq,
                '',
                n,
                cases,
                ''
            ]
            writer.writerow(output_row)
            rows_written += 1

            if len(preview_rows) < preview_limit:
                preview_rows.append(output_row)

    print('Canonical output preview:')
    print(chr(9).join(canonical_header))
    for row in preview_rows:
        print(chr(9).join(row))

    return {'rows_written': rows_written}