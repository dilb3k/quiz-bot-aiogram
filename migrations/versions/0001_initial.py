"""Initial immutable PostgreSQL schema."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    """CREATE TABLE users (id BIGINT PRIMARY KEY, name VARCHAR(256) NOT NULL,
role VARCHAR(16) NOT NULL DEFAULT 'user', CHECK (role IN ('user','admin','superadmin')))""",
    """CREATE TABLE chats (id BIGINT PRIMARY KEY, title VARCHAR(256) NOT NULL,
kind VARCHAR(16) NOT NULL, enabled BOOLEAN NOT NULL, reason TEXT)""",
    """CREATE TABLE chat_managers (chat_id BIGINT REFERENCES chats(id) ON UPDATE CASCADE,
user_id BIGINT REFERENCES users(id), checked_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(chat_id,user_id))""",
    """CREATE TABLE categories (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, active BOOLEAN NOT NULL)""",
    """CREATE TABLE questions (id SERIAL PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES categories(id),
text VARCHAR(300) NOT NULL, correct INTEGER NOT NULL CHECK(correct BETWEEN 0 AND 3),
explanation VARCHAR(200) NOT NULL, active BOOLEAN NOT NULL, seed_key VARCHAR(80) UNIQUE)""",
    "CREATE INDEX ix_questions_category_id ON questions(category_id)",
    """CREATE TABLE question_options (question_id INTEGER REFERENCES questions(id), position INTEGER CHECK(position BETWEEN 0 AND 3),
text VARCHAR(100) NOT NULL, PRIMARY KEY(question_id,position))""",
    """CREATE TABLE quiz_sessions (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL REFERENCES chats(id) ON UPDATE CASCADE,
owner_id BIGINT NOT NULL REFERENCES users(id), category_id INTEGER NOT NULL REFERENCES categories(id),
source_session_id INTEGER REFERENCES quiz_sessions(id), status VARCHAR(16) NOT NULL CHECK(status IN ('active','paused','stopping','finished','blocked')),
interval INTEGER NOT NULL CHECK(interval BETWEEN 60 AND 86400), duration INTEGER NOT NULL CHECK(duration BETWEEN 5 AND 2628000),
total INTEGER CHECK(total IS NULL OR total > 0), sent INTEGER NOT NULL, queue JSONB NOT NULL,
next_run_at TIMESTAMPTZ, lease_until TIMESTAMPTZ, lease_token VARCHAR(36), attempts INTEGER NOT NULL,
reason TEXT, created_at TIMESTAMPTZ NOT NULL)""",
    "CREATE INDEX ix_quiz_sessions_chat_id ON quiz_sessions(chat_id)",
    "CREATE UNIQUE INDEX one_live_session_per_chat ON quiz_sessions(chat_id) WHERE status IN ('active','paused','stopping')",
    "CREATE INDEX session_due ON quiz_sessions(status,next_run_at)",
    """CREATE TABLE session_questions (id SERIAL PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES quiz_sessions(id),
question_id INTEGER NOT NULL REFERENCES questions(id), poll_id VARCHAR(128) UNIQUE,
chat_id BIGINT NOT NULL REFERENCES chats(id) ON UPDATE CASCADE, message_id BIGINT, snapshot JSONB NOT NULL, correct INTEGER NOT NULL,
status VARCHAR(16) NOT NULL CHECK(status IN ('sending','open','closed','uncertain','failed')),
sent_at TIMESTAMPTZ NOT NULL, closes_at TIMESTAMPTZ NOT NULL, closed_at TIMESTAMPTZ, aggregate JSONB NOT NULL, poll_update_id BIGINT NOT NULL)""",
    "CREATE INDEX ix_session_questions_session_id ON session_questions(session_id)",
    "CREATE UNIQUE INDEX one_open_question ON session_questions(session_id) WHERE status IN ('sending','open')",
    """CREATE TABLE answers (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
session_question_id INTEGER NOT NULL REFERENCES session_questions(id), option INTEGER, correct BOOLEAN NOT NULL,
points INTEGER NOT NULL CHECK(points IN (0,1)), received_at TIMESTAMPTZ NOT NULL, elapsed_ms BIGINT NOT NULL CHECK(elapsed_ms >= 0),
update_id BIGINT NOT NULL, UNIQUE(user_id,session_question_id))""",
    "CREATE INDEX ix_answers_user_id ON answers(user_id)",
    "CREATE INDEX ix_answers_session_question_id ON answers(session_question_id)",
    "CREATE TABLE fsm_records (key VARCHAR(200) PRIMARY KEY, state VARCHAR(200), data JSONB NOT NULL)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in [
        "fsm_records",
        "answers",
        "session_questions",
        "quiz_sessions",
        "question_options",
        "questions",
        "categories",
        "chat_managers",
        "chats",
        "users",
    ]:
        op.drop_table(table)
