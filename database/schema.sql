CREATE TABLE IF NOT EXISTS guilds (
    id bigint PRIMARY KEY,
    prefix text
);

ALTER TABLE guilds ADD COLUMN IF NOT EXISTS recorder_role_id bigint;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS recap_channel_id bigint;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS retention_days integer;

CREATE TABLE IF NOT EXISTS voice_sessions (
    id uuid PRIMARY KEY,
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    started_by bigint NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    status text NOT NULL DEFAULT 'recording',
    seconds_recorded integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    error text,
    title text,
    transcript text,
    recap text,
    search tsvector GENERATED ALWAYS AS
        (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(transcript, '') || ' ' || coalesce(recap, ''))) STORED
);

CREATE INDEX IF NOT EXISTS voice_sessions_search_idx ON voice_sessions USING gin (search);
CREATE INDEX IF NOT EXISTS voice_sessions_guild_idx ON voice_sessions (guild_id, started_at DESC);

CREATE TABLE IF NOT EXISTS voice_consent (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    status text NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS voice_usage (
    guild_id bigint NOT NULL,
    month date NOT NULL,
    seconds_used integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, month)
);