# turkish-parliament-texts

## Install

    wget http://voltran.cmpe.boun.edu.tr/temporary_download/datasets/tbmm/tbmm-corpus-v0.1.tar.gz
    tar -zxvf tbmm-corpus-v0.1.tar.gz
    
    pip3 install pipenv
    pipenv install --python 3
    
## Run
     
Example code to save a figure:
   
    pipenv shell
    ipython
    import corpus_loader
    plot_values, counts, total_count, all_keywords = corpus_loader.corpus.plot_word_freqs_given_a_regexp(r"^mebus", keyword="mebus")
    
    plot_values, counts, total_count, all_keywords = corpus_loader.corpus.plot_word_freqs_given_a_regexp_for_each_year(r"^(milletvekil|vekil)", keyword="milletvekil",)
   
    
## Preprocessing

Run below command to test the new clean text suit.

    python3 cleaning_text_files.py
