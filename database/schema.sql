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

CREATE TABLE IF NOT EXISTS brainrot_guilds (
    guild_id bigint PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT false,
    channel_ids bigint[] NOT NULL DEFAULT '{}',
    added_terms text[] NOT NULL DEFAULT '{}',
    removed_terms text[] NOT NULL DEFAULT '{}',
    allowed_terms text[] NOT NULL DEFAULT '{}',
    exempt_role_ids bigint[] NOT NULL DEFAULT '{}',
    exempt_user_ids bigint[] NOT NULL DEFAULT '{}',
    mute_mode text NOT NULL DEFAULT 'timeout',
    mute_role_id bigint,
    mute_seconds integer NOT NULL DEFAULT 300,
    ladder_seconds integer[] NOT NULL DEFAULT '{1800,7200,86400}',
    warn_delete_seconds integer NOT NULL DEFAULT 30,
    delete_messages boolean NOT NULL DEFAULT false,
    include_mods boolean NOT NULL DEFAULT false,
    modlog_channel_id bigint
);

-- heat numbers, counters, and timestamps only; never message content
CREATE TABLE IF NOT EXISTS brainrot_users (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    heat integer NOT NULL DEFAULT 0,
    heat_updated_at timestamptz NOT NULL,
    window_started_at timestamptz,
    window_count integer NOT NULL DEFAULT 0,
    lifetime_offenses integer NOT NULL DEFAULT 0,
    repeat_until timestamptz,
    escalation_level integer NOT NULL DEFAULT 0,
    mute_expires_at timestamptz,
    muted_role_id bigint,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS brainrot_users_lifetime_idx ON brainrot_users (guild_id, lifetime_offenses DESC);
CREATE INDEX IF NOT EXISTS brainrot_users_mute_idx ON brainrot_users (mute_expires_at) WHERE muted_role_id IS NOT NULL;

-- what the module did and when, for the dashboard's activity feed; numbers and ids only, never message content
CREATE TABLE IF NOT EXISTS brainrot_actions (
    id bigserial PRIMARY KEY,
    guild_id bigint NOT NULL,
    at timestamptz NOT NULL,
    action text NOT NULL,
    source text NOT NULL,
    applied boolean NOT NULL DEFAULT true,
    target_user_id bigint,
    actor_user_id bigint,
    heat integer,
    heat_added integer,
    duration_seconds integer,
    escalation_level integer,
    field text,
    before text,
    after text
);

CREATE INDEX IF NOT EXISTS brainrot_actions_guild_idx ON brainrot_actions (guild_id, at DESC);

-- activity counts for the developer insights and a future dashboard: numbers, ids, dates, and command names only;
-- never message content. Daily rows are pruned after 90 days; a server's rows go 7 days after the bot leaves it,
-- or the moment it runs `stats off`.
CREATE TABLE IF NOT EXISTS stats_guilds (
    guild_id bigint PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT true,
    tracking_since timestamptz,
    left_at timestamptz
);

CREATE TABLE IF NOT EXISTS stats_guild_days (
    guild_id bigint NOT NULL,
    day date NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    joins integer NOT NULL DEFAULT 0,
    leaves integer NOT NULL DEFAULT 0,
    commands integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day)
);

CREATE TABLE IF NOT EXISTS stats_channel_days (
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    day date NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, channel_id, day)
);

CREATE TABLE IF NOT EXISTS stats_hour_days (
    guild_id bigint NOT NULL,
    day date NOT NULL,
    hour smallint NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day, hour)
);

CREATE TABLE IF NOT EXISTS stats_user_days (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    day date NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    commands integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, day)
);

CREATE TABLE IF NOT EXISTS stats_user_channel_days (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    day date NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, channel_id, day)
);

CREATE TABLE IF NOT EXISTS stats_user_hour_days (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    day date NOT NULL,
    hour smallint NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, day, hour)
);

CREATE TABLE IF NOT EXISTS stats_command_days (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    command text NOT NULL,
    day date NOT NULL,
    uses integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, command, day)
);

CREATE INDEX IF NOT EXISTS stats_user_days_guild_day_idx ON stats_user_days (guild_id, day);
CREATE INDEX IF NOT EXISTS stats_channel_days_guild_day_idx ON stats_channel_days (guild_id, day);
CREATE INDEX IF NOT EXISTS stats_user_channel_days_user_idx ON stats_user_channel_days (user_id);
CREATE INDEX IF NOT EXISTS stats_user_hour_days_user_idx ON stats_user_hour_days (user_id);
CREATE INDEX IF NOT EXISTS stats_command_days_user_idx ON stats_command_days (user_id);
CREATE INDEX IF NOT EXISTS stats_user_days_user_idx ON stats_user_days (user_id);
