import codecs
from collections import defaultdict as dd
from functools import cmp_to_key

import logging
import os
import re

from six import itervalues, iteritems

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from gensim.corpora.textcorpus import TextCorpus
from gensim.corpora.dictionary import Dictionary

from utils import tokenize, print_err
from year_mapping import term2year, year2term
logger = logging.getLogger(__name__)


def _compare_two_document_labels(coded_filepaths):
    """

    :type left: str
    :param left:
    :param right:
    :return:
    """

    """
    ***tbmm/d01-y1 'den tbmm/d11-y3 'e***
    tbmm/d11-y3 'den baslayarak ***tbt-ty01 ... tbt-ty19 'a***
    tbt-ty19 'dan sonra
    ***mgk/mgk-d00***
    sonra
    ***tbmm/d17-y1 'den baslayarak tbmm/d24-y3 'e*** kadar
    """

    # re.match(r"^tbmm/", x)

    def compare(left, right):

        if coded_filepaths[left[1]] < coded_filepaths[right[1]]:
            return -1
        elif coded_filepaths[left[1]] > coded_filepaths[right[1]]:
            return 1
        else:
            if left[1] < right[1]:
                return -1
            elif left[1] == right[1]:
                return 0
            else:
                return 1

    return compare

class TbmmCorpus(TextCorpus):

    def __init__(self, input=None, dictionary=None, metadata=False, character_filters=None,
                 tokenizer=None, token_filters=None,
                 config=None):
        super().__init__(input, dictionary, metadata, character_filters, tokenizer, token_filters)

        self.documents = {}
        self.documents_metadata = {}

        self.metadata2description = {}

        self.documents_word_counts = {}

        self.dictionary.debug = True

        self.config = config

        self.date_mappings = {}

        # Calculated if calculate_intervals called
        self.documents_date_groups = None

        # Calculated if calculate_stats called
        self.stats = None

    @staticmethod
    def filter_extremes(dictionary_object, no_below=5, no_above=0.5, keep_n=100000, keep_tokens=None):
        """
        Filter out tokens that appear in

        1. less than `no_below` documents (absolute number) or
        2. more than `no_above` documents (fraction of total corpus size, *not*
           absolute number).
        3. if tokens are given in keep_tokens (list of strings), they will be kept regardless of
           the `no_below` and `no_above` settings
        4. after (1), (2) and (3), keep only the first `keep_n` most frequent tokens (or
           keep all if `None`).

        After the pruning, shrink resulting gaps in word ids.

        **Note**: Due to the gap shrinking, the same word may have a different
        word id before and after the call to this function!
        """
        assert isinstance(dictionary_object, Dictionary), "The object must be an instance of Dictionary"
        no_above_abs = int(
            no_above * dictionary_object.num_docs)  # convert fractional threshold to absolute threshold

        # determine which tokens to keep
        if keep_tokens:
            keep_ids = [dictionary_object.token2id[v] for v in keep_tokens if v in dictionary_object.token2id]
            good_ids = (
                v for v in itervalues(dictionary_object.token2id)
                if no_below <= dictionary_object.dfs.get(v, 0) <= no_above_abs or v in keep_ids
            )
        else:
            good_ids = (
                v for v in itervalues(dictionary_object.token2id)
                if no_below <= dictionary_object.dfs.get(v, 0) <= no_above_abs
            )
        good_ids = sorted(good_ids, key=dictionary_object.dfs.get, reverse=True)
        if keep_n is not None:
            good_ids = good_ids[:keep_n]
        bad_words = [(dictionary_object[idx], dictionary_object.dfs.get(idx, 0)) for idx in
                     set(dictionary_object).difference(good_ids)]
        logger.info("discarding %i tokens: %s...", len(dictionary_object) - len(good_ids), bad_words[:10])
        logger.info(
            "keeping %i tokens which were in no less than %i and no more than %i (=%.1f%%) documents",
            len(good_ids), no_below, no_above_abs, 100.0 * no_above
        )

        logger.info("resulting dictionary: %s", dictionary_object)
        return good_ids, (len(dictionary_object) - len(good_ids))

    @staticmethod
    def filter_tokens(dictionary_object, bad_ids=None, good_ids=None, compact_ids=True):
        """
        Remove the selected `bad_ids` tokens from all dictionary mappings, or, keep
        selected `good_ids` in the mapping and remove the rest.

        `bad_ids` and `good_ids` are collections of word ids to be removed.
        """
        assert isinstance(dictionary_object, Dictionary), "The object must be an instance of Dictionary"
        if bad_ids is not None:
            bad_ids = set(bad_ids)
            dictionary_object.token2id = {token: tokenid for token, tokenid in iteritems(dictionary_object.token2id) if
                                          tokenid not in bad_ids}
            dictionary_object.dfs = {tokenid: freq for tokenid, freq in iteritems(dictionary_object.dfs) if
                                     tokenid not in bad_ids}
        if good_ids is not None:
            good_ids = set(good_ids)
            dictionary_object.token2id = {token: tokenid for token, tokenid in iteritems(dictionary_object.token2id) if
                                          tokenid in good_ids}
            dictionary_object.dfs = {tokenid: freq for tokenid, freq in iteritems(dictionary_object.dfs) if
                                     tokenid in good_ids}
        if compact_ids:
            dictionary_object.compactify()

    def add_document(self, document, filepath):
        self.dictionary.add_documents([document],
                                      prune_at=None)
        self.documents[len(self.documents)+1] = self.dictionary.doc2idx(document)

        self.documents_metadata[len(self.documents)] = {
            'filepath': filepath
        }

        # if len(self.documents) % 100 == 0:
        #     print_err("n_documents: %d" % len(self.documents))
        #     good_ids, n_removed = TbmmCorpus.filter_extremes(self.dictionary, no_below=0, no_above=1, keep_n=2000000)
        #     # do the actual filtering, then rebuild dictionary to remove gaps in ids
        #     TbmmCorpus.filter_tokens(self.dictionary, good_ids=good_ids, compact_ids=False)
        #
        #     logger.info("tbmmcorpus rebuilding dictionary, shrinking gaps")
        #
        #     # build mapping from old id -> new id
        #     idmap = dict(zip(sorted(itervalues(self.dictionary.token2id)), range(len(self.dictionary.token2id))))
        #
        #     # reassign mappings to new ids
        #     self.dictionary.token2id = {token: idmap[tokenid] for token, tokenid in iteritems(self.dictionary.token2id)}
        #     self.dictionary.id2token = {}
        #     self.dictionary.dfs = {idmap[tokenid]: freq for tokenid, freq in iteritems(self.dictionary.dfs)}
        #
        #     if n_removed:
        #         logger.info("Starting to remap word ids in tbmmcorpus documents hashmap")
        #         # def check_and_replace(x):
        #         #     if x in idmap:
        #         #         return x
        #         #     else:
        #         #         return -1
        #         for idx, (doc_id, document) in enumerate(self.documents.items()):
        #             if idx % 1000 == 0:
        #                 logger.info("remapping: %d documents finished" % idx)
        #             # self.documents[doc_id] = [check_and_replace(oldid) for oldid in document]
        #             self.documents[doc_id] = [idmap[oldid] for oldid in document if oldid in idmap]

    def getstream(self):
        return super().getstream()

    def preprocess_text(self, text):
        return tokenize(text)

    def get_texts(self):
        if self.metadata:
            for idx, (documentno, document_text_in_ids) in enumerate(self.documents.items()):
                if idx % 1000 == 0:
                    print_err("get_texts:", documentno)
                document_text = [self.dictionary[id] for id in document_text_in_ids]
                yield self.preprocess_text(" ".join(document_text)), \
                      (documentno, self.documents_metadata[documentno])
        else:
            for idx, (documentno, document_text_in_ids) in enumerate(self.documents.items()):
                if idx % 1000 == 0:
                    print_err("get_texts:", documentno)
                document_text = [self.dictionary[id] for id in document_text_in_ids]
                yield self.preprocess_text(" ".join(document_text))

    def __len__(self):
        return len(self.documents)

    def __iter__(self):
        """The function that defines a corpus.

        Iterating over the corpus must yield sparse vectors, one for each document.
        """
        if self.metadata:
            for text, metadata in self.get_texts():
                yield self.dictionary.doc2bow(text, allow_update=False), metadata
        else:
            for text in self.get_texts():
                yield self.dictionary.doc2bow(text, allow_update=False)

    def save_tbmm_corpus(self, fname):
        # example code:
        # logger.info("converting corpus to ??? format: %s", fname)
        with codecs.open(fname, 'w', encoding='utf-8') as fout:
            for ((doc_id, document), (doc_id, metadata)) in zip(self.documents.items(), self.documents_metadata.items()):  # iterate over the document stream
                fmt = " ".join([str(x) for x in document])  # format the document appropriately...
                fout.write("%d %s %s\n" % (doc_id, metadata['filepath'], fmt))  # serialize the formatted document to disk

        self.dictionary.save(fname + ".vocabulary")
        self.dictionary.save_as_text(fname + ".vocabulary.txt")

    def load_tbmm_corpus(self, fname):
        with codecs.open(fname, 'r', encoding='utf-8') as f:
            line_idx = 0
            line = f.readline()
            while line:
                tokens = line.strip().split(" ")
                metadata = {}
                doc_id = int(tokens[0])
                metadata['filepath'] = tokens[1]
                document = [int(t) for t in tokens[2:]]

                self.documents[doc_id] = document
                self.documents_metadata[doc_id] = metadata

                line_idx += 1
                if line_idx % 100 == 0:
                    logger.info("loaded %d documents" % line_idx)

                line = f.readline()

        self.dictionary = self.dictionary.load_from_text(fname + ".vocabulary.txt")

        # Date mappings object has a complex structure
        # it is a dictionary with Terms as keys and
        # value is a dictionary which has keys as file url
        # and value as their publish dates
        # finally with one special item as shown below
        #  'd18-y4': {
        #    ...
        #    'https://www.tbmm.gov.tr/tutanaklar/TUTANAK/TBMM/d18/c046/tbmm18046126.pdf': datetime.date(1990, 8, 2),
        #    'https://www.tbmm.gov.tr/tutanaklar/TUTANAK/TBMM/d18/c046/tbmm18046127.pdf': datetime.date(1990, 8, 4),
        #    'interval': [datetime.date(1989, 11, 5), datetime.date(1990, 8, 4)]
        # }
        import pickle
        with open(fname + '.date_mappings_2.pkl', 'rb') as f:
            self.date_mappings = pickle.load(f)


    @staticmethod
    def get_document_topics(corpus, lda, document):
        """

        :type lda: gensim.models.ldamodel.LdaModel
        :param lda:
        :param document: we expect ids
        :return:
        """

        document_bow = TbmmCorpus.doc2bow_from_word_ids(document)

        return document_bow, lda.get_document_topics(document_bow, per_word_topics=False)

    @staticmethod
    def doc2bow_from_word_ids(document):
        counter = dd(int)
        for word_idx in document:
            counter[word_idx] += 1
        document_bow = sorted(iteritems(counter))
        return document_bow

    @staticmethod
    def count_howmany_given_word_ids(document_bow, target_word_ids):
        target_freq_for_this_document = \
            sum([freq for word_id, freq in document_bow if word_id in target_word_ids])
        return target_freq_for_this_document


    def generate_word_counts(self):

        for idx, (doc_id, document) in enumerate(self.documents.items()):
            self.documents_word_counts[doc_id] = TbmmCorpus.doc2bow_from_word_ids(document)

            if idx % 1000 == 0:
                logger.info("word_counts: %d documents" % idx)

    def query_word_count_across_all_documents(self, target_word_id_or_ids, threshold=1):

        if not isinstance(target_word_id_or_ids, list):
            target_word_ids = [target_word_id_or_ids]
        else:
            target_word_ids = target_word_id_or_ids

        total_count = 0
        counts = dd(int)

        for idx, (doc_id, document_word_counts) in enumerate(self.documents_word_counts.items()):
            target_freq_for_this_document = \
                [freq for word_id, freq in document_word_counts if word_id in target_word_ids]

            target_freq_for_this_document = \
                TbmmCorpus.count_howmany_given_word_ids(document_word_counts, target_word_ids)

            if target_freq_for_this_document >= threshold:
                # target_freq_for_this_document = target_freq_for_this_document[0]

                filepath = self.documents_metadata[doc_id]['filepath']

                # tokens = self.metadata2description[filepath]

                counts[filepath] += target_freq_for_this_document
                total_count += target_freq_for_this_document

                # main_type = tokens[0]
                # second_type_and_term = tokens[1]
                # pdf_filename = tokens[3]
                #
                #
                # if main_type not in counts:
                #     counts[main_type] = dict()
                #     counts[main_type][second_type_and_term] = dict()
                #     counts[main_type][second_type_and_term][pdf_filename] = target_freq_for_this_document
                # else:
                #     if second_type_and_term not in counts[main_type]:
                #         counts[main_type][second_type_and_term] = dict()
                #         counts[main_type][second_type_and_term][
                #             pdf_filename] = target_freq_for_this_document
                #     else:
                #         counts[main_type][second_type_and_term][
                #             pdf_filename] = target_freq_for_this_document

            if idx % 1000 == 0:
                logger.info("%d documents scanned for word_id")
        return counts, total_count

    def plot_word_freqs_given_a_regexp(self, regexp_to_select_keywords, keyword="default", format="pdf", threshold=1):
        """

        :param regexp_to_select_keywords: r"^(siki|sıkı)y(o|ö)net(i|ı)m"
        :return:
        """
        all_keywords = [(x, y) for x, y in self.dictionary.token2id.items() if
         re.match(regexp_to_select_keywords, x)]

        counts, total_count = self.query_word_count_across_all_documents([x[1] for x in all_keywords], threshold=threshold)

        # # filter only tbmm documents for now
        # plot_values = sorted([(x, y) for x, y in counts.items() if re.match(r"^tbmm/", x)],
        #                      key=lambda x: x[0])

        plot_values = [(x, y) for y, x in sorted([(y, x) for x, y in counts.items() if re.match(r"^(tbmm|tbt|mgk)/", x)],
                                                 key=cmp_to_key(self.compare_two_document_labels))]

        self.plot_single_values_for_documents(os.path.join(self.config["plots_dir"], keyword),
                                              plot_values,
                                              format=format)
        return plot_values, counts, total_count, all_keywords

    def plot_word_freqs_given_a_regexp_for_each_year(self, lo_regexp_to_select_keywords, legend_labels, keyword="default", format="pdf"):
        fig = plt.figure(figsize=(16, 9), dpi=300)
        plt.gca().spines['top'].set_visible(False)
        plt.gca().spines['right'].set_visible(False)
        linestyles = ['-', '--', '-.', ':']
        legends = []
        handles = []
        for idx, regexp_to_select_keywords in enumerate(lo_regexp_to_select_keywords):
            donem_dict_normalized, counts, total_count, all_keywords = self._word_freqs_given_a_regexp_for_each_year(regexp_to_select_keywords)
            plot_values = donem_dict_normalized
            plot_values = sorted(donem_dict_normalized.items(), key=lambda x: x[0])
            linestyle = linestyles.pop()
            line, = plt.plot([x[0] for x in plot_values], [x[1] for x in plot_values],
                             label=legend_labels[idx],
                             linestyle=linestyle)
            handles += [line]
            legends.append(regexp_to_select_keywords)

            #plt.xticks(range(0, len(plot_values), 100),
            #           [plot_values[i][0].split("/")[1] for i in range(0, len(plot_values), 100)],
            #           rotation='vertical')

        plt.legend(handles=handles)

        #plt.margins(0.2)
        plt.subplots_adjust(bottom=0.15)
        filename = os.path.join(self.config["plots_dir"], keyword+"_normalized")
        fig.savefig(filename + "." + format)
        # import ipdb ; ipdb.set_trace()

    def _word_freqs_given_a_regexp_for_each_year(self, regexp_to_select_keywords):
        """

        :param regexp_to_select_keywords: r"^(siki|sıkı)y(o|ö)net(i|ı)m"
        :return:
        """

        all_keywords = [(x, y) for x, y in self.dictionary.token2id.items() if
                        re.match(regexp_to_select_keywords, x)]

        counts, total_count = self.query_word_count_across_all_documents([x[1] for x in all_keywords], threshold=1)

        # # filter only tbmm documents for now
        # plot_values = sorted([(x, y) for x, y in counts.items() if re.match(r"^tbmm/", x)],
        #                      key=lambda x: x[0])

        plot_values = [(x, y) for x, y in counts.items() if re.match(r"^(tbmm|tbt|mgk)/", x)]


        donem_dict = dd(int) ; donem_doc_count = dd(int) ; donem_dict_normalized = dd(int)

        for x,y in plot_values:
             term_str = x.split("/")[1]
             donem_dict[term_str] += y
             donem_doc_count[term_str] +=1

        for term in donem_dict.keys():
             donem_dict_normalized[term2year[term]] = donem_dict[term] / donem_doc_count[term]

        return donem_dict_normalized, counts, total_count, all_keywords

    def _plot_single_values_for_documents(self, plot_values):

        fig = plt.figure(figsize=(16, 9), dpi=300)

        plt.plot(range(len(plot_values)), [x[1] for x in plot_values],
                 marker='+', markersize=3,
                 linestyle="None")

        plt.xticks(range(0, len(plot_values), 100),
                   [plot_values[i][0].split("/")[1] for i in range(0, len(plot_values), 100)],
                   rotation='vertical')
        plt.margins(0.2)
        plt.subplots_adjust(bottom=0.15)

        return fig

    def plot_single_values_for_documents(self, filename, plot_values, format="pdf"):
        fig = self._plot_single_values_for_documents(plot_values)

        fig.savefig(filename + "." + format)
        fig.clear()

    def calculate_topic_distributions_of_all_documents(self, lda):
        """

        :param lda:
        :type lda: gensim.models.ldamodel.LdaModel
        :return:
        """
        n_topics = lda.num_topics
        topic_dist_matrix = []
        label_vector = []

        unsorted_filepaths = [(doc_id, x['filepath']) for doc_id, x in self.documents_metadata.items() if
                              re.match(r"^(tbmm|tbt|mgk)/", x['filepath'])]

        for idx, (doc_id, filepath) in enumerate(unsorted_filepaths):
            document_bow = self.documents_word_counts[doc_id]
            topic_dist = lda.get_document_topics(document_bow)
            topic_dist_full_vector = [0] * n_topics
            for topic_id, prob in topic_dist:
                topic_dist_full_vector[topic_id] = prob
            topic_dist_matrix += [topic_dist_full_vector]
            label_vector += [filepath]

        return topic_dist_matrix, label_vector

    # def plot_topic_by_year(self, topic_no, topic_dist_matrix, label_vector, format="pdf"):
    #     # import ipdb ; ipdb.set_trace()
    #     fig = plt.figure()
    #     sorted_zipped_topic_dist_matrix = sorted(zip(topic_dist_matrix, label_vector),
    #                                              key=cmp_to_key(self.compare_two_document_labels))
    #
    #     tbmm_topic_dist_matrix = sorted_zipped_topic_dist_matrix
    #
    #     plot_values = [(value[1], value[0][topic_no]) for id, value in enumerate(tbmm_topic_dist_matrix)]
    #
    #     plt.plot([x[0] for x in plot_values] , [x[1] for x in plot_values], label="Topic %d" % topic_no)
    #     plt.subplots_adjust(bottom=0.15)
    #     filename = os.path.join(self.config["plots_dir"], "topic_%d" % topic_no)
    #     fig.savefig(filename + "." + format)

    def plot_a_specific_topic_by_year(self, topics, topic_dist_matrix, label_vector, legend_labels, keyword="default_topic", format="pdf"):
        fig = plt.figure(figsize=(16, 9), dpi=300)
        plt.gca().spines['top'].set_visible(False)
        plt.gca().spines['right'].set_visible(False)
        linestyles = ['-', '--', '-.', ':']
        markerstyles = ['+', '.', 'o', 'v', '^']

        handles = []
        for idx, topic_no in enumerate(topics):

            donem_dict_normalized = self._get_topic_normalized_for_each_year(topic_no,
                                                                             topic_dist_matrix,
                                                                             label_vector)

            plot_values = sorted(donem_dict_normalized.items(), key=lambda x: x[0])
            if idx < len(linestyles):
                linestyle = linestyles[-(idx+1)]
                markerstyle = ""
            else:
                linestyle = linestyles[0]
                markerstyle = markerstyles[-(idx+1)]

            line, = plt.plot([x[0] for x in plot_values], [x[1] for x in plot_values],
                             label=legend_labels[idx],
                             linestyle=linestyle,
                             marker=markerstyle)
            handles += [line]

            #plt.xticks(range(0, len(plot_values), 100),
            #           [plot_values[i][0].split("/")[1] for i in range(0, len(plot_values), 100)],
            #           rotation='vertical')

        plt.legend(handles=handles)

        #plt.margins(0.2)
        plt.subplots_adjust(bottom=0.15)
        filename = os.path.join(self.config["plots_dir"], keyword+"_normalized")
        fig.savefig(filename + "." + format)
        # import ipdb ; ipdb.set_trace()

    def _get_topic_normalized_for_each_year(self, topic_no, topic_dist_matrix, label_vector):

        donem_dict = dd(int)
        donem_doc_count = dd(int)
        donem_dict_normalized = dd(int)

        for idx, label in enumerate(label_vector):
            term_str = label.split("/")[1]
            donem_dict[term_str] += topic_dist_matrix[idx][topic_no]
            donem_doc_count[term_str] += 1

        for term in donem_dict.keys():
             donem_dict_normalized[term2year[term]] = donem_dict[term] / donem_doc_count[term]

        return donem_dict_normalized

    def plot_topic_across_time(self, topic_no, topic_dist_matrix, label_vector, format="pdf"):

        # sorted_zipped_topic_dist_matrix = sorted(zip(topic_dist_matrix, label_vector),
        #                                          key=lambda x: x[1])

        sorted_zipped_topic_dist_matrix = sorted(zip(topic_dist_matrix, label_vector),
                                                 key=cmp_to_key(self.compare_two_document_labels))

        # tbmm_topic_dist_matrix = [x for x in sorted_zipped_topic_dist_matrix if
        #                           re.match(r"^tbmm/", x[1])]

        tbmm_topic_dist_matrix = sorted_zipped_topic_dist_matrix

        plot_values = [(value[1], value[0][topic_no]) for id, value in enumerate(tbmm_topic_dist_matrix)]

        self.plot_single_values_for_documents(os.path.join(self.config["plots_dir"], "topic_%d" % topic_no),
                                              plot_values,
                                              format=format)




    def prepare_metadata_to_description_dictionary(self):
        """
        The entry in metadata dictionary
        kurucu-meclis/milli-birlik-komitesi-d00/mbk_00002fih/
        Corresponding description is in this CSV file
        resources/urls/kurucu-meclis/milli-birlik-komitesi-d00.csv
        as this line
        "https://www.tbmm.gov.tr/tutanaklar/TUTANAK/MBK_/d00/c002/mbk_00002fih.pdf", 2. Cilt Fihristi
        :return:
        """

        assert self.config, "we need to know where the resources/urls directory is"

        import csv
        import glob
        import re

        for idx, filepath in enumerate(glob.iglob(self.config["resources_dir"] + '/**/*.csv', recursive=True)):
            m = re.match(r"{resources_dir}([^/]+)/([^/]+).csv".format(resources_dir=self.config["resources_dir"]),
                         filepath)
            if m:
                first_level_dir = m.group(1)
                csv_filename = m.group(2)
                donem_no = csv_filename.split("-")[-1]
                with open(filepath, mode="r", newline='') as f:
                    rows = list(csv.reader(f, delimiter=',', quotechar='"'))
                    for row in rows[1:]:
                        m_url = re.match(r".*/([^/]+).pdf$", row[0])
                        if m_url:
                            pdf_filename = m_url.group(1)
                            self.metadata2description[
                                "/".join([first_level_dir, csv_filename, pdf_filename, ''])] \
                                = [first_level_dir, csv_filename, donem_no, pdf_filename,
                                   row[1].strip()]
                        else:
                            logger.warning("incompatible url: " + row[0])

        unsorted_filepaths = [y for y in
                              sorted([x['filepath'] for x in self.documents_metadata.values()]) if
                              re.match(r"^(tbmm|tbt|mgk)/", y)]

        coded_filepaths = {}
        for filepath in unsorted_filepaths:
            if re.match(r"^tbmm/d(01|02|03|04|05|06|07|08|09|10|11)", filepath):
                code = 1
            elif re.match(r"^tbt/", filepath):
                code = 2
            elif re.match(r"^mgk/", filepath):
                code = 3
            elif re.match(r"^tbmm/d(17|18|19|20|21|22|23|24)", filepath):
                code = 4
            else:
                code = 0
            coded_filepaths[filepath] = code

        self.compare_two_document_labels = _compare_two_document_labels(coded_filepaths)

    def calculate_intervals(self):

        years = sorted(year2term.keys())
        change_points = [1923, 1938, 1946, 1960, 1980, 1991, 2002]

        codes = {1923: []}
        point = 0
        for year in years:
            if year < (change_points[point + 1] if point + 1 < len(change_points) else 5000):
                codes[change_points[point]] += year2term[year]
            else:
                point += 1
                codes[change_points[point]] = []

        term2id = {}
        for _id, v in self.documents_metadata.items():
            term = v['filepath'].split('/')[1]
            if term in term2id:
                term2id[term].append(_id)
            else:
                term2id[term] = [_id]

        merged_dates = {}
        for date, arr in codes.items():
            for code in arr:
                if date in merged_dates:
                    if code in term2id:
                        merged_dates[date] += term2id[code]
                    else:
                        print('{} not exists in metadata!'.format(code))
                else:
                    if code in term2id:
                        merged_dates[date] = term2id[code]
                    else:
                        print('{} not exists in metadata!'.format(code))

        self.documents_date_groups = merged_dates

    def calculate_stats(self):
        self.stats = {
            'unique_word_counts': {},
            'document_word_counts': {},
            'unique_word_counts_per_year': {},
            'document_word_counts_per_year': {},
            'days_a_year': {}
        }

        # Get bow values from self.documents_word_counts
        # which has vocabulary as keys and
        # word count as sum of their counts
        for d_id, bow in self.documents_word_counts.items():
            self.stats['unique_word_counts'][d_id] = len(bow)
            self.stats['document_word_counts'][d_id] = sum([c for (w_id, c) in bow])

        # Look load_tbmm_corpus for date_mapping structure
        # r_date_mappings is the reduced version of date mappings
        # it does not have 'interval' items
        # it has file names as keys instead of HTTP location
        r_date_mappings = {term: {addr.split('/')[-1][:-4]: _date
                                  for addr, _date in dd.items() if addr != 'interval'}
                           for term, dd in self.date_mappings.items()}


        # Two different objects to navigate on

        # doc2id_time is a dictionary with file names as keys and
        # document_id, time(as Date object) tuple as values
        doc2id_time = {}

        # time2id_doc is a dictionary with time as keys and
        # file name, document_id tuple as values
        time2id_doc = {}
        for _id, v in self.documents_metadata.items():
            # Ex metadata item: (1, {'filepath': 'tbt/tbt-ty05/tbmm05005fih/'})
            # key is document_id and
            # value is a dictionary with 'filepath' item which has the value
            # <Type of Doc?>/<Term>/<Document Name>
            term, document_name = v['filepath'].split('/')[1:3]

            # Curation of doc2id_time and time2id_doc
            # it is possible to add term values or create different type of
            # dictionaries to work on...
            if term in r_date_mappings:
                if document_name in r_date_mappings[term]:
                    doc_t = r_date_mappings[term][document_name]

                    id_time = (_id, doc_t)
                    if document_name in doc2id_time:
                        doc2id_time[document_name].append(id_time)
                    else:
                        doc2id_time[document_name] = [id_time]

                    id_doc = (_id, document_name)
                    if doc_t in time2id_doc:
                        time2id_doc[doc_t].append(id_doc)
                    else:
                        time2id_doc[doc_t] = [id_doc]

        # Similar to unique_word_counts and document_word_counts
        # but by the help of time2id_doc, this part calculates
        # days_a_year, unique_word_counts_per_year and document_word_counts_per_year
        for document_date in sorted(list(time2id_doc)):
            current_year = document_date.year

            # days_a_year holds day count for a year that a publish happened
            # and document count for a year
            # {
            #   ...
            #   2013: {'day_count': 63, 'document_count': 93}
            # }
            # In 2013, there are 93 published documents in 63 days..
            document_for_date = len(time2id_doc[document_date])
            if current_year in self.stats['days_a_year']:
                self.stats['days_a_year'][current_year]['day_count'] += 1
                self.stats['days_a_year'][current_year]['document_count'] += document_for_date
            else:
                self.stats['days_a_year'][current_year] = {'day_count': 1, 'document_count': document_for_date}

            for (d_id, doc) in time2id_doc[document_date]:
                bow = self.documents_word_counts[d_id]

                if current_year in self.stats['unique_word_counts_per_year']:
                    self.stats['unique_word_counts_per_year'][current_year] += len(bow)
                    self.stats['document_word_counts_per_year'][current_year] += sum([c for (w_id, c) in bow])
                else:
                    self.stats['unique_word_counts_per_year'][current_year] = len(bow)
                    self.stats['document_word_counts_per_year'][current_year] = sum([c for (w_id, c) in bow])


def prepare_for_analysis():
    import configparser

    config_parser = configparser.ConfigParser()
    config_parser.read("config.ini")
    config = config_parser['default']

    from tbmmcorpus import TbmmCorpus

    corpus = TbmmCorpus(metadata=True, config=config)

    corpus.load_tbmm_corpus("corpus-v0.1/tbmm_corpus.mm")

    corpus.prepare_metadata_to_description_dictionary()

    corpus.generate_word_counts()

    from gensim.models.ldamodel import LdaModel
    lda = LdaModel.load("tbmm_lda.model.passes_100")

    import matplotlib
    matplotlib.use('Agg')  # Must be before importing matplotlib.pyplot or pylab!
    import matplotlib.pyplot as plt

    topic_dist_matrix, label_vector = corpus.calculate_topic_distributions_of_all_documents(lda)

    for topic_no in range(1, 20):
        corpus.plot_topic_across_time(topic_no, topic_dist_matrix, label_vector)

    corpus.plot_word_freqs_given_a_regexp(r"^lokavt", keyword="lokavt")

    corpus.plot_word_freqs_given_a_regexp(r"^mebus", keyword="mebus")




if __name__ == "__main__":

    import configparser

    config_parser = configparser.ConfigParser()
    config_parser.read("config.ini")
    config = config_parser['default']

    from tbmmcorpus import TbmmCorpus

    corpus = TbmmCorpus(metadata=True, config=config)

    corpus.prepare_metadata_to_description_dictionary()

    # corpus.load_tbmm_corpus("tbmm_corpus.mm")
    #
    # from gensim.models.ldamodel import LdaModel
    #
    # lda = LdaModel.load("tbmm_lda.model")
