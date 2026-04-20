CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE operators (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                     citext UNIQUE NOT NULL,
    password_hash             text NOT NULL,
    created_at                timestamptz NOT NULL DEFAULT now(),
    last_password_change_at   timestamptz NOT NULL DEFAULT now()
);
