import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .errors import ConfigurationError


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def text_key(text):
    return digest(re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip())


class VectorStore:
    def __init__(self, settings, embeddings):
        self.settings = settings
        settings.runtime.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.runtime / 'chroma'),
                         settings=chromadb.Settings(anonymized_telemetry=False))
        # A changed embedding model requires a separate index; never mix dimensions/models.
        profile_path = settings.runtime / 'index-profile.json'
        expected = {'embedding_model': os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
                    'base_url': os.getenv('OPENAI_BASE_URL', '').rstrip('/')}
        if profile_path.exists():
            if json.loads(profile_path.read_text(encoding='utf-8')) != expected:
                raise ConfigurationError('임베딩 모델 또는 서버가 기존 색인과 다릅니다. 별도 runtime 폴더로 새로 색인하세요.')
        else:
            profile_path.write_text(json.dumps(expected), encoding='utf-8')
        options = {'client': self.client, 'embedding_function': embeddings,
                   'collection_metadata': {'hnsw:space': 'cosine'}}
        self.meta = Chroma(collection_name=settings.metadata_collection, **options)
        self.docs = Chroma(collection_name=settings.documents_collection, **options)

    def count(self, name):
        collection = self.client.get_collection(self.settings.metadata_collection if name == 'meta'
                                                else self.settings.documents_collection)
        return collection.count()

    def index_catalog(self, catalog):
        records = [Document(page_content=s.text(), metadata=s.metadata() | {'chunk_id': f'meta:{s.species_id}'})
                   for s in catalog.items]
        ids = [doc.metadata['chunk_id'] for doc in records]
        for start in range(0, len(records), 64):
            self.meta.add_documents(records[start:start+64], ids=ids[start:start+64])
        return self.count('meta')

    def metadata_for(self, species_id):
        value = self.meta.get(ids=[f'meta:{species_id}'], include=['documents', 'metadatas'])
        return [Document(page_content=t, metadata=m)
                for t, m in zip(value.get('documents') or [], value.get('metadatas') or [])]

    def index_document(self, species_id, source):
        splitter = RecursiveCharacterTextSplitter(chunk_size=self.settings.chunk_size,
                    chunk_overlap=self.settings.chunk_overlap, length_function=len,
                    separators=['\n\n', '\n', '。', '. ', ' ', ''])
        documents, ids = [], []
        counter = 0
        # A PDF page remains a citation unit; chunks never cross its boundary.
        for page in source['pages']:
            for text in splitter.split_text(page['text']):
                if not text.strip():
                    continue
                chunk_id = f"doc:{species_id}:{source['document_id']}:{counter}"
                metadata = {key: source[key] for key in (
                    'document_id', 'document_title', 'source_type', 'source_url',
                    'license', 'collected_at')}
                metadata |= {'species_id': species_id, 'chunk_index': counter,
                             'chunk_id': chunk_id, 'content_hash': text_key(text),
                             'search_query': source.get('search_query', ''),
                             'source_file': source.get('source_file', ''),
                             'revision_id': str(source.get('revision_id', ''))}
                metadata['is_subject'] = bool(source.get('is_subject', False))
                metadata.update({key: source[key] for key in ('record_kind', 'taxon_group', 'endangered_grade',
                    'modification_notice') if key in source})
                if page.get('page_number'):
                    metadata['page_number'] = page['page_number']
                documents.append(Document(page_content=text, metadata=metadata))
                ids.append(chunk_id)
                counter += 1
        if not documents:
            return 0
        # Upsert first, remove stale tail chunks after success. Rechunking cannot leave old evidence.
        where = {'$and': [{'species_id': species_id}, {'document_id': source['document_id']}]}
        existing = self.docs.get(where=where, include=['documents', 'metadatas'])
        previous = existing['ids']
        old = {key: (text, meta) for key, text, meta in zip(previous, existing['documents'], existing['metadatas'])}
        new = {key: (doc.page_content, doc.metadata) for key, doc in zip(ids, documents)}
        if old == new:
            return len(documents)
        for start in range(0, len(documents), 64):
            self.docs.add_documents(documents[start:start+64], ids=ids[start:start+64])
        stale = sorted(set(previous) - set(ids))
        if stale:
            self.docs.delete(ids=stale)
        return len(documents)

    def retrieve_external(self, species_id, query):
        options = {'k': self.settings.top_k, 'filter': {'species_id': species_id}}
        if self.settings.search_type == 'mmr':
            matches = self.docs.max_marginal_relevance_search(query,
                        fetch_k=self.settings.mmr_fetch_k, lambda_mult=self.settings.mmr_lambda, **options)
        else:
            matches = self.docs.similarity_search(query, **options)
        topics = [('서식 환경', r'서식|서식지'), ('국내 분포', r'국내|분포'), ('주요 위협 요인', r'위협|멸종 원인')]
        requested = [label for label, pattern in topics if re.search(pattern, query)]
        if len(requested) > 1:
            balanced = []
            for label in requested:
                balanced.extend(self.docs.similarity_search(label, k=1,
                    filter={'species_id': species_id}))
            seen = set()
            matches = [doc for doc in balanced + matches if not (
                doc.metadata['chunk_id'] in seen or seen.add(doc.metadata['chunk_id']))]
        if requested:
            # Exact item facts must not lose their evidence slots to long generic articles.
            saved = self.docs.get(where={'$and': [{'species_id': species_id}, {'record_kind': 'ecology_fact'}]},
                                  include=['documents', 'metadatas'])
            facts = [Document(page_content=text, metadata=metadata)
                     for text, metadata in zip(saved['documents'], saved['metadatas'])]
            score = lambda doc: sum(bool(re.search(r'^' + re.escape(label) + r'\s*\(', doc.page_content, re.M)) for label in requested)
            facts = sorted((doc for doc in facts if score(doc)), key=score, reverse=True)
            seen = set()
            matches = [doc for doc in facts + matches if not (
                doc.metadata['chunk_id'] in seen or seen.add(doc.metadata['chunk_id']))]
        # Reserve one external evidence slot for the subject itself. Broad context
        # documents must not crowd its own biology out of the comparison.
        subject = self.docs.similarity_search(query, k=1, filter={
            '$and': [{'species_id': species_id}, {'is_subject': True}]})
        if subject:
            subject_id = subject[0].metadata['chunk_id']
            matches = subject + [d for d in matches if d.metadata['chunk_id'] != subject_id]
        return matches[:self.settings.top_k]

    def search_catalog(self, query, filters=None):
        return self.meta.similarity_search(query, k=self.settings.catalog_candidates, filter=filters)

    def search_ecology_candidates(self, query, filters=None):
        terms = [{'record_kind': 'ecology_fact'}]
        if filters:
            terms.extend(filters.get('$and', [filters]))
        where = {'$and': terms} if len(terms) > 1 else terms[0]
        return self.docs.similarity_search(query, k=self.settings.catalog_candidates, filter=where)


def merge_evidence(documents):
    unique, seen_ids, seen_text = [], set(), set()
    for doc in documents:
        sid = doc.metadata.get('species_id', '')
        chunk_id = doc.metadata.get('chunk_id', '')
        # Preserve species ownership when the same source is shared by two comparison subjects.
        content_id = (sid, text_key(doc.page_content))
        if chunk_id in seen_ids or content_id in seen_text:
            continue
        seen_ids.add(chunk_id)
        seen_text.add(content_id)
        unique.append({'evidence_id': len(unique)+1, 'text': doc.page_content,
                       'metadata': dict(doc.metadata)})
    return unique
