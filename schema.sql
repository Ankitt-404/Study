CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS subjects (
    id              SERIAL PRIMARY KEY,
    semester        INT  NOT NULL,
    code            TEXT,                       -- some courses have no code yet
    name            TEXT NOT NULL,
    category        TEXT,                       -- MC, ME, MDC, AEC, NV
    credits         INT  NOT NULL,
    lecture_hours   INT  NOT NULL DEFAULT 0,    -- L
    tutorial_hours  INT  NOT NULL DEFAULT 0,    -- T
    practical_hours INT  NOT NULL DEFAULT 0,    -- P
    skill_hours     INT  NOT NULL DEFAULT 0,    -- S
    is_lab          BOOLEAN NOT NULL DEFAULT FALSE,
    elective_group  TEXT,                       -- links alternatives, e.g. 'sem3-elective'
    UNIQUE (semester, name)
);

CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    subject_id  INT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    semester    INT NOT NULL,
    section     TEXT,                           -- 'Module outline', 'Course outcomes', 'Books', 'Practicals'
    module      TEXT,                           -- e.g. 'Module IV: Trees'
    pages       TEXT,                           -- e.g. '74-75'
    content     TEXT NOT NULL,
    embedding   vector(384) NOT NULL,           -- must match bge-small
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_semester_idx ON chunks (semester);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (content_tsv);