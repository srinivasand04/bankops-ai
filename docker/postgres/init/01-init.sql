-- Runs once, when the data volume is first created.
-- Separate database for the automated test suite.
CREATE DATABASE bankops_test;

-- pgvector is installed in the image; enable it for the later RAG phase.
CREATE EXTENSION IF NOT EXISTS vector;
\connect bankops_test
CREATE EXTENSION IF NOT EXISTS vector;
