import collections
import os
import uuid
import re

from core.utils import chain_and_flatten
from public_interface.models import Genes


class Dataset(object):
    """
    Base class to create datasets from Seq objects into FASTA, TNT formats.
    """
    def __init__(self, codon_positions, partition_by_positions, seq_objs, gene_codes,
                 voucher_codes, file_format, outgroup=None, voucher_codes_metadata=None,
                 minimum_number_of_genes=None, aminoacids=None):
        self.minimum_number_of_genes = minimum_number_of_genes
        self.outgroup = outgroup
        self.file_format = file_format
        self.codon_positions = codon_positions
        self.aminoacids = aminoacids
        self.partition_by_positions = partition_by_positions
        # need to sort our seq_objs dictionary by gene_code
        self.seq_objs = collections.OrderedDict(sorted(seq_objs.items(), key=lambda t: t[0]))
        self.gene_codes = gene_codes
        self.voucher_codes = voucher_codes
        self.reading_frames = self.get_reading_frames()
        self.voucher_codes_metadata = voucher_codes_metadata
        self.warnings = []
        self.partition_list = None

        self.cwd = os.path.dirname(__file__)
        self.guid = self.make_guid()
        self.dataset_file = os.path.join(self.cwd,
                                         'dataset_files',
                                         self.file_format + '_' + self.guid + '.txt',
                                         )

    def save_dataset_to_file(self, dataset_str):
        with open(self.dataset_file, 'w') as handle:
            handle.write(dataset_str)

    def make_guid(self):
        return uuid.uuid4().hex

    def get_number_chars_from_partition_list(self, partitions):
        chars = 0
        gene_codes_and_lengths = collections.OrderedDict()

        i = 0
        gene_code = ''
        for item in partitions[0]:
            if item.startswith('\n'):
                if self.file_format == 'NEXUS' or self.file_format == 'PHY':
                    gene_code = item.strip().replace('[', '').replace(']', '')
                    continue
                if self.file_format == 'TNT':
                    gene_code = 'dummy' + str(i)
                    i += 1
                    continue
            if gene_code != '':
                first_entry = re.sub('\s+', ' ', item)
                voucher, sequence = first_entry.split(' ')
                chars += len(sequence)
                gene_codes_and_lengths[gene_code] = len(sequence)
                gene_code = ''
        self.gene_codes_and_lengths = gene_codes_and_lengths
        self.number_chars = chars

    def get_number_of_genes_for_taxa(self, partitions):
        number_of_genes_for_taxa = dict()
        vouchers_to_drop = set()

        gene_code = ''
        for item in partitions[0]:
            if item.startswith('\n'):
                    if self.file_format == 'NEXUS' or self.file_format == 'PHY':
                        gene_code = item.strip().replace('[', '').replace(']', '')
                        continue
                    if self.file_format == 'TNT':
                        gene_code = 'dummy'
                        continue
            if gene_code != '':
                entry = re.sub('\s+', ' ', item)
                voucher, sequence = entry.split(' ')

                if voucher not in number_of_genes_for_taxa:
                    number_of_genes_for_taxa[voucher] = 0

                sequence = sequence.replace('?', '')
                if sequence != '':
                    number_of_genes_for_taxa[voucher] += 1

        if self.minimum_number_of_genes is None:
            self.vouchers_to_drop = []
        else:
            for voucher in number_of_genes_for_taxa:
                if number_of_genes_for_taxa[voucher] < self.minimum_number_of_genes:
                    vouchers_to_drop.add(voucher)
            self.vouchers_to_drop = vouchers_to_drop

    def get_reading_frames(self):
        """

        :return: dict of gene_code: reading_frame. If not found, flag warning.
        """
        reading_frames = dict()
        genes = Genes.objects.all().values('gene_code', 'reading_frame')
        for gene in genes:
            gene_code = gene['gene_code']
            if gene_code in self.gene_codes:
                reading_frames[gene_code] = gene['reading_frame']
        return reading_frames

    def split_sequence_in_codon_positions(self, gene_code, seq):
        """Puts the sequence in frame, by deleting base pairs at the beginning
        of the sequence if the reading frame is not 1.

        Retuns tuple of nucleotides based on codon positions.

        :param gene_code: as lower case
        :param seq: as BioPython seq object.
        :return: tuple of seq strings.

        Example:
            If reading frame is 2: ATGGGG becomes TGGGG. Then the sequence is
            processed to extract the codon positions requested by the user.

        """
        reading_frame = int(self.reading_frames[gene_code]) - 1
        seq = seq[reading_frame:]

        # This is the BioPython way to get codon positions
        # http://biopython.org/DIST/docs/tutorial/Tutorial.html#htoc19
        first_position = seq[0::3]
        second_position = seq[1::3]
        third_position = seq[2::3]
        return first_position, second_position, third_position

    def convert_lists_to_dataset(self, partitions):
        """
        Method to override in order to add headers and footers depending
        on needed dataset.
        """
        out = ''
        for i in partitions:
            out += '\n'
            out += '\n'.join(i)
        dataset_str = out.strip()
        self.save_dataset_to_file(dataset_str)
        return dataset_str

    def get_codons_in_each_partition(self, codons):
        partition_list = ()
        codon_descriptions = []
        codon_pos = []
        for i in codons:
            partition_list += ([],)
            if i == '1st':
                codon_descriptions.append('_1st_codon')
                codon_pos.append(0)
            if i == '2nd':
                codon_descriptions.append('_2nd_codon')
                codon_pos.append(1)
            if i == '3rd':
                codon_descriptions.append('_3rd_codon')
                codon_pos.append(2)
        for gene_code in self.seq_objs:
            this_gene = None

            for seq_record in self.seq_objs[gene_code]:
                if self.reading_frames[gene_code] is None:
                    self.warnings.append("Reading frame for gene %s hasn't been specified so "
                                         "it cannot be included in your dataset." % gene_code)
                    continue

                if this_gene is None:
                    this_gene = seq_record.name

                    for i in range(len(codon_descriptions)):
                        seq_str = self.get_gene_divisor(this_gene, codon_descriptions[i])
                        partition_list[i].append(seq_str)

                codons = self.split_sequence_in_codon_positions(this_gene,
                                                                seq_record.seq)
                for i in range(len(codon_pos)):
                    seq_str = self.format_record_id_and_seq_for_dataset(seq_record.id, codons[codon_pos[i]])
                    partition_list[i].append(seq_str)
        return partition_list

    def get_gene_divisor(self, this_gene, codon_description=None):
        if self.file_format == 'FASTA':
            seq_str = '>' + this_gene
            if codon_description is not None:
                seq_str += codon_description
            seq_str += '\n' + '--------------------'

        if self.file_format == 'PHY':
            seq_str = '\n[%s]' % this_gene

        if self.file_format == 'TNT':
            seq_str = '\n[&dna]'

        if self.file_format == 'NEXUS':
            seq_str = '\n[%s]' % this_gene
        return seq_str

    def format_record_id_and_seq_for_dataset(self, seq_record_id, seq_record_seq):
        if self.file_format == 'FASTA':
            seq_str = '>' + seq_record_id + '\n' + str(seq_record_seq)
        if self.file_format == 'NEXUS' or \
                self.file_format == 'PHY' or \
                self.file_format == 'TNT':
            seq_str = str(seq_record_id).ljust(55) + str(seq_record_seq)
        return seq_str

    def get_codons_in_one_partition(self, codons):
        partition_list = ([],)
        codon_pos = []
        for i in codons:
            if i == '1st':
                codon_pos.append(0)
            if i == '2nd':
                codon_pos.append(1)
            if i == '3rd':
                codon_pos.append(2)
        for gene_code in self.seq_objs:
            this_gene = None

            for seq_record in self.seq_objs[gene_code]:
                if self.reading_frames[gene_code] is None:
                    self.warnings.append("Reading frame for gene %s hasn't been specified so "
                                         "it cannot be included in your dataset." % gene_code)
                    continue

                if this_gene is None:
                    this_gene = seq_record.name

                    gene_divisor = self.get_gene_divisor(this_gene)
                    partition_list[0].append(gene_divisor)

                codons = self.split_sequence_in_codon_positions(this_gene,
                                                                seq_record.seq)

                codon_seqs = str(chain_and_flatten([codons[i] for i in codon_pos]))
                seq_str = self.format_record_id_and_seq_for_dataset(seq_record.id, codon_seqs)

                partition_list[0].append(seq_str)
        self.partition_list = partition_list
        return partition_list

    def from_seq_objs_to_dataset(self):
        """Take a list of BioPython's sequence objects and return a FASTA string

        Returns:
            The FASTA string will contain the gene_code at the top as if it were
            another FASTA gene sequence.

        """
        if '1st' in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                'ALL' not in self.codon_positions and \
                'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                'ALL' not in self.codon_positions and \
                'ONE' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '2nd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['2nd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '2nd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                'ONE' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['2nd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '3rd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                'ONE' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '3rd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '2nd' in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                'ALL' not in self.codon_positions and \
                'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st', '2nd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '2nd' in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                'ALL' not in self.codon_positions and \
                'ONE' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_one_partition(['1st', '2nd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '3rd' in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '3rd' in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '3rd' in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                'ONE' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_one_partition(['1st', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '2nd' in self.codon_positions and '3rd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['2nd', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '2nd' in self.codon_positions and '3rd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                'ONE' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_one_partition(['2nd', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '2nd' in self.codon_positions and '3rd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['2nd', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if ('ALL' in self.codon_positions or
                ('1st' in self.codon_positions and '2nd' in self.codon_positions and '3rd' in self.codon_positions)) \
                and 'EACH' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st', '2nd', '3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if ('ALL' in self.codon_positions or
                ('1st' in self.codon_positions and '2nd' in self.codon_positions and '3rd' in self.codon_positions)) \
                and 'ONE' in self.partition_by_positions:
            self.partition_list = ([],)
            for gene_code in self.seq_objs:
                this_gene = None
                for seq_record in self.seq_objs[gene_code]:
                    if this_gene is None:
                        this_gene = seq_record.name

                        seq_str = self.get_gene_divisor(this_gene)
                        self.partition_list[0].append(seq_str)

                    seq_str = self.format_record_id_and_seq_for_dataset(seq_record.id, seq_record.seq)
                    self.partition_list[0].append(seq_str)
            return self.convert_lists_to_dataset(self.partition_list)

        if 'ALL' in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = ([], [],)

            for gene_code in self.seq_objs:
                if self.reading_frames[gene_code] is None:
                    self.warnings.append("Reading frame for gene %s hasn't been specified so "
                                         "it cannot be included in your dataset." % gene_code)
                    continue

                this_gene = None
                for seq_record in self.seq_objs[gene_code]:
                    if this_gene is None:
                        this_gene = seq_record.name

                        seq_str = '>' + this_gene + '_1st_2nd_codons\n' + '--------------------'
                        self.partition_list[0].append(seq_str)

                        seq_str = '>' + this_gene + '_3rd_codon\n' + '--------------------'
                        self.partition_list[1].append(seq_str)

                    codons = self.split_sequence_in_codon_positions(this_gene, seq_record.seq)

                    seq_str = '>' + seq_record.id + '\n' + str(chain_and_flatten([codons[0], codons[1]]))
                    self.partition_list[0].append(seq_str)

                    seq_str = '>' + seq_record.id + '\n' + str(codons[2])
                    self.partition_list[1].append(seq_str)
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['1st'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '2nd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['2nd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '3rd' in self.codon_positions and \
                '1st' not in self.codon_positions and \
                '2nd' not in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = self.get_codons_in_each_partition(['3rd'])
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '2nd' in self.codon_positions and \
                '3rd' not in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = ([],)
            for gene_code in self.seq_objs:
                this_gene = None
                for seq_record in self.seq_objs[gene_code]:
                    if self.reading_frames[gene_code] is None:
                        self.warnings.append("Reading frame for gene %s hasn't been specified so "
                                             "it cannot be included in your dataset." % gene_code)
                        continue

                    if this_gene is None:
                        this_gene = seq_record.name

                        seq_str = '>' + this_gene + '_1st_2nd_codons\n' + '--------------------'
                        self.partition_list[0].append(seq_str)

                    codons = self.split_sequence_in_codon_positions(this_gene, seq_record.seq)

                    seq_str = '>' + seq_record.id + '\n' + str(chain_and_flatten([codons[0], codons[1]]))
                    self.partition_list[0].append(seq_str)
            return self.convert_lists_to_dataset(self.partition_list)

        if '1st' in self.codon_positions and '2nd' in self.codon_positions and \
                '3rd' in self.codon_positions and \
                '1st2nd_3rd' in self.partition_by_positions:
            self.partition_list = ([], [],)
            for gene_code in self.seq_objs:
                this_gene = None
                for seq_record in self.seq_objs[gene_code]:
                    if self.reading_frames[gene_code] is None:
                        self.warnings.append("Reading frame for gene %s hasn't been specified so "
                                             "it cannot be included in your dataset." % gene_code)
                        continue

                    if this_gene is None:
                        this_gene = seq_record.name

                        seq_str = '>' + this_gene + '_1st_2nd_codons\n' + '--------------------'
                        self.partition_list[0].append(seq_str)

                        seq_str = '>' + this_gene + '_3rd_codon\n' + '--------------------'
                        self.partition_list[1].append(seq_str)

                    codons = self.split_sequence_in_codon_positions(this_gene, seq_record.seq)

                    seq_str = '>' + seq_record.id + '\n' + str(chain_and_flatten([codons[0], codons[1]]))
                    self.partition_list[0].append(seq_str)

                    seq_str = '>' + seq_record.id + '\n' + str(codons[2])
                    self.partition_list[1].append(seq_str)
            return self.convert_lists_to_dataset(self.partition_list)

    def get_datasets_as_aminoacids(self, partitions):
        """Queries sequences and creates protein strings and list of
        items with accession number (code, gene_code, accession).
        """
        sequence_models = Sequences.objects.all()
        voucher_models = Vouchers.objects.all().values('genus', 'species', 'code')
        gene_models = Genes.objects.all().values()
        for sequence_model in sequence_models:
            code = sequence_model.code_id
            gene_code = sequence_model.gene_code
            gene = self.get_gene_from_gene_models(gene_code, gene_models)
            if code in self.voucher_codes and gene_code in self.gene_codes:
                if sequence_model.accession.strip() != '':
                    self.items_with_accession.append(
                        {
                            'voucher_code': code,
                            'gene_code': gene_code,
                            'accession': sequence_model.accession,
                        },
                    )
                else:
                    for v in voucher_models:
                        if v['code'] == code:
                            seq_id = v['genus'] + '_' + v['species'] + '_' + code
                            seq_description = '[org=' + v['genus'] + ' ' + v['species'] + ']'
                            seq_description += ' [Specimen-voucher=' + code + ']'
                            seq_description += ' [note=' + gene['description'] + ' gene, partial cds.]'
                            seq_description += ' [Lineage=]'
                            seq_seq = sequence_model.sequences

                    # # DNA sequences
                    seq_seq = utils.strip_question_marks(seq_seq)[0]
                    if '?' in seq_seq or 'N' in seq_seq.upper():
                        seq_obj = Seq(seq_seq, IUPAC.ambiguous_dna)
                    else:
                        seq_obj = Seq(seq_seq, IUPAC.unambiguous_dna)

                    self.fasta += '>' + seq_id + ' ' + seq_description + '\n'
                    self.fasta += str(seq_obj) + '\n'

                    protein = utils.translate_to_protein(
                        gene,
                        sequence_model,
                        seq_description,
                        seq_id,
                    )
                    if not protein.startswith('Error'):
                        self.protein += protein
                    else:
                        self.warnings.append("Could not translate %s: %s" % (seq_id, protein))

        with open(self.fasta_file, 'w') as handle:
            handle.write(self.fasta)

        with open(self.protein_file, 'w') as handle:
            handle.write(self.protein)