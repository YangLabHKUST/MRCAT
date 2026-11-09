import gzip
import csv
import re


MISSING = {'', '.', 'NA', 'N/A', 'NULL', 'NaN', 'nan'}
CANONICAL_HEADER = [
    'SNP', 'CHR', 'BP', 'effect_allele', 'other_allele', 'beta', 'or', 'se', 'z',
    'pval', 'neglog10_pval', 'freq_qc', 'info', 'n', 'n_cases', 'n_controls'
]


def _norm_field(v):
    if v is None:
        return ''
    s = str(v)
    if s.strip() in MISSING:
        return ''
    return s


def _extract_rsid(v):
    s = _norm_field(v)
    if not s:
        return ''
    m = re.search(r'rs\d+', s)
    return m.group(0) if m else ''


def _is_nucleotide_allele(v):
    s = _norm_field(v)
    if not s:
        return ''
    return s if all(c in 'ACGTacgt' for c in s) else ''


def _cell(row, i):
    return row[i] if i < len(row) else ''


def _open_input(path):
    p = str(path).lower()
    if p.endswith(('.gz', '.bgz', '.bgzip')):
        return gzip.open(path, 'rt', encoding='utf-8', newline='')
    return open(path, 'r', encoding='utf-8', newline='')


def _open_output(path):
    p = str(path).lower()
    if p.endswith(('.gz', '.bgz', '.bgzip')):
        return gzip.open(path, 'wt', encoding='utf-8', newline='')
    return open(path, 'w', encoding='utf-8', newline='')


def transform(input_path, output_path, context):
    delimiter = '\t'
    if isinstance(context, dict) and context.get('input_delimiter'):
        d = context['input_delimiter']
        if d and d != 'whitespace':
            delimiter = d

    with _open_input(input_path) as fin:
        reader = csv.reader(fin, delimiter=delimiter)
        raw_header = next(reader)
        header = [h.lstrip('#') for h in raw_header]
        idx = {name: i for i, name in enumerate(header)}

        required = ['chrom', 'pos', 'ref', 'alt', 'rsids', 'pval', 'mlogp', 'beta', 'sebeta', 'af_alt']
        missing = [c for c in required if c not in idx]
        if missing:
            raise ValueError('Missing required source columns: {}'.format(', '.join(missing)))

        i_chrom = idx['chrom']
        i_pos = idx['pos']
        i_ref = idx['ref']
        i_alt = idx['alt']
        i_rsids = idx['rsids']
        i_pval = idx['pval']
        i_mlogp = idx['mlogp']
        i_beta = idx['beta']
        i_sebeta = idx['sebeta']
        i_af_alt = idx['af_alt']

        with _open_output(output_path) as fout:
            writer = csv.writer(fout, delimiter='\t', lineterminator='\n')
            writer.writerow(CANONICAL_HEADER)
            print('\t'.join(CANONICAL_HEADER))

            rows_written = 0
            preview_count = 0
            for row in reader:
                if not row or all(_norm_field(x) == '' for x in row):
                    continue

                chrom = _norm_field(_cell(row, i_chrom))
                bp = _norm_field(_cell(row, i_pos))
                snp = _extract_rsid(_cell(row, i_rsids))

                ref = _is_nucleotide_allele(_cell(row, i_ref))
                alt = _is_nucleotide_allele(_cell(row, i_alt))
                if ref and alt:
                    effect_allele = alt
                    other_allele = ref
                else:
                    effect_allele = ''
                    other_allele = ''

                beta = _norm_field(_cell(row, i_beta))
                se = _norm_field(_cell(row, i_sebeta))
                pval = _norm_field(_cell(row, i_pval))
                mlogp = _norm_field(_cell(row, i_mlogp))
                freq_qc = _norm_field(_cell(row, i_af_alt))

                out_row = [
                    snp, chrom, bp, effect_allele, other_allele, beta, '', se, '',
                    pval, mlogp, freq_qc, '', '', '', ''
                ]
                writer.writerow(out_row)
                rows_written += 1

                if preview_count < 10:
                    print('\t'.join(out_row))
                    preview_count += 1

        side_n = context.get('sample_size') if isinstance(context, dict) else None
        return {
            'rows_written': rows_written,
            'side_sample_size': side_n,
            'effect_allele_source': 'alt',
            'other_allele_source': 'ref',
            'freq_qc_source': 'af_alt'
        }
