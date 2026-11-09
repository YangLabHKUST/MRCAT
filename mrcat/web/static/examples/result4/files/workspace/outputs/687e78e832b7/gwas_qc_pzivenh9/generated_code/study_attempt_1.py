import gzip
import csv

def _clean(value):
    if value is None:
        return ''
    s = str(value).strip()
    if s == '' or s == '.' or s.upper() in ('NA', 'N/A', 'NULL', 'NAN'):
        return ''
    return s

def _extract_rsid(value):
    if not value:
        return ''
    s = str(value)
    lower = s.lower()
    idx = lower.find('rs')
    while idx != -1:
        j = idx + 2
        while j < len(s) and s[j].isdigit():
            j += 1
        if j > idx + 2:
            if idx == 0 or not (s[idx - 1].isalnum() or s[idx - 1] == '_'):
                return s[idx:j]
        idx = lower.find('rs', idx + 1)
    return ''

def _is_nucleotide(allele):
    if not allele:
        return False
    return all(c in 'ACGTacgt' for c in allele)

def transform(input_path, output_path, context):
    canonical = [
        'SNP', 'CHR', 'BP', 'effect_allele', 'other_allele',
        'beta', 'or', 'se', 'z', 'pval', 'neglog10_pval',
        'freq_qc', 'info', 'n', 'n_cases', 'n_controls'
    ]
    source_columns = [
        'variant_id', 'effect_allele', 'other_allele',
        'effect_allele_frequency', 'beta', 'standard_error',
        'p_value', 'chromosome', 'base_pair_location'
    ]
    input_name = str(input_path)
    if input_name.lower().endswith(('.gz', '.bgz', '.bgzip', '.vcf.gz')):
        input_f = gzip.open(input_path, 'rt', encoding='utf-8', newline='')
    else:
        input_f = open(input_path, 'r', encoding='utf-8', newline='')

    with input_f:
        reader = csv.reader(input_f, delimiter=chr(9))
        header = next(reader, None)
        if header is None:
            raise RuntimeError('Empty input file')
        header = [h.strip() if h else '' for h in header]
        missing = [name for name in source_columns if name not in header]
        if missing:
            raise RuntimeError('Missing required source columns: ' + ', '.join(missing))
        col = {name: header.index(name) for name in source_columns}
        rows_written = 0
        rows_symbolic = 0
        with open(output_path, 'w', encoding='utf-8', newline='') as out_f:
            writer = csv.writer(out_f, delimiter=chr(9), lineterminator=chr(10))
            writer.writerow(canonical)
            for row in reader:
                if not row:
                    continue
                def get_value(name):
                    idx = col[name]
                    return row[idx] if idx < len(row) else ''

                variant_id = _clean(get_value('variant_id'))
                snp = _extract_rsid(variant_id)
                chrom = _clean(get_value('chromosome'))
                bp = _clean(get_value('base_pair_location'))
                ea = _clean(get_value('effect_allele'))
                oa = _clean(get_value('other_allele'))
                if _is_nucleotide(ea) and _is_nucleotide(oa):
                    effect_allele = ea
                    other_allele = oa
                else:
                    effect_allele = ''
                    other_allele = ''
                    if ea and not _is_nucleotide(ea):
                        rows_symbolic += 1
                    if oa and not _is_nucleotide(oa):
                        rows_symbolic += 1
                beta = _clean(get_value('beta'))
                se = _clean(get_value('standard_error'))
                pval = _clean(get_value('p_value'))
                freq_qc = _clean(get_value('effect_allele_frequency'))

                out_row = [
                    snp, chrom, bp, effect_allele, other_allele,
                    beta, '', se, '', pval, '', freq_qc,
                    '', '', '', ''
                ]
                writer.writerow(out_row)
                rows_written += 1

    return {
        'rows_written': rows_written,
        'rows_with_symbolic_alleles': rows_symbolic
    }