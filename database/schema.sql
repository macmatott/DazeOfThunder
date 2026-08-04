-- Formula Fantasy — Core Schema
-- Target: Supabase (Postgres + Row Level Security)
--
-- Design notes:
-- - Raw results are immutable once imported; corrections supersede rather
--   than mutate, so standings can always be recomputed from source data.
-- - Every "points" table is a *derived* table, not hand-edited — if scoring
--   rules change, recompute from race_results / f1_race_results, don't
--   patch totals directly.
-- - Constructor pairing is intentionally NOT hard-coded to exactly 2
--   members (league size is 11, which doesn't split evenly) — see the
--   constructor_members join table below.

-- ============================================================
-- Auth / Identity
-- ============================================================

-- Supabase Auth (auth.users) handles login. This table extends it with
-- league-specific profile data and links to the stable iRacing identity.
create table public.participants (
    id uuid primary key default gen_random_uuid(),
    auth_user_id uuid unique references auth.users(id) on delete set null,

    display_name text not null,
    is_admin boolean not null default false,
    is_active boolean not null default true,

    -- Stable iRacing identity — the key CSV rows are matched against.
    -- Nullable: a participant can exist before their iRacing account is linked.
    iracing_cust_id bigint unique,
    iracing_display_name text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.participants is
    'A Formula Fantasy league member. auth_user_id links to Supabase Auth; '
    'iracing_cust_id is the stable key for matching iRacing CSV rows.';

-- ============================================================
-- Seasons
-- ============================================================

create table public.seasons (
    id uuid primary key default gen_random_uuid(),
    name text not null,                    -- e.g. '2027'
    is_active boolean not null default false,
    draft_locked boolean not null default false,
    created_at timestamptz not null default now()
);

-- ============================================================
-- iRacing race events + results
-- ============================================================

create table public.race_events (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),

    -- Extracted from the export filename (eventresult_<id>_0.csv), not the
    -- CSV body — confirmed the iRacing event id is filename-only.
    iracing_event_id bigint not null unique,

    track text not null,
    series text not null,
    start_time timestamptz not null,

    -- iRacing's own season bookkeeping — separate from our `seasons` table.
    iracing_season_year int,
    iracing_season_quarter int,
    race_week int,
    strength_of_field int,
    special_event_type text,

    -- Maps this iRacing race to a round on the real F1 calendar. Nullable
    -- at import time — the CSV has no such link, an admin supplies it
    -- (e.g. "this counts as Round 7 — Hungary").
    ff_round_name text,
    ff_round_number int,

    -- Correction path: bad imports are superseded, never edited/deleted,
    -- so the audit trail and reproducibility guarantee both hold.
    is_superseded boolean not null default false,
    superseded_by_id uuid references public.race_events(id),

    source_filename text not null,
    imported_by uuid references public.participants(id),
    imported_at timestamptz not null default now()
);

create table public.race_results (
    id uuid primary key default gen_random_uuid(),
    race_event_id uuid not null references public.race_events(id) on delete cascade,

    -- Nullable: null = this iRacing driver hasn't been matched to a
    -- registered participant. Row is stored in full regardless — unknown
    -- drivers are flagged for admin review, never silently dropped.
    participant_id uuid references public.participants(id),

    iracing_cust_id bigint not null,
    iracing_display_name text not null,

    finish_position int not null,
    start_position int not null,
    car_name text,
    car_class text,
    car_number text,

    status text not null,               -- Running / Disconnected / Disqualified / DNS / etc.
    interval text,                       -- raw string, e.g. "-1 L" or "-09.068"
    laps_led int not null default 0,
    laps_completed int not null default 0,
    incidents int not null default 0,

    qualify_time text,                   -- raw, formats are inconsistent in practice
    average_lap_time text,
    fastest_lap_time text,
    fastest_lap_number int,

    -- iRacing's own native points — reference data, NOT league scoring.
    iracing_points int,
    iracing_club_points int,

    old_irating int,
    new_irating int,

    is_ai boolean not null default false,

    created_at timestamptz not null default now(),

    unique (race_event_id, iracing_cust_id)
);

-- Derived: sim racing points actually awarded under league scoring rules.
-- Kept separate from race_results so rescoring never touches raw data.
create table public.sim_points_awarded (
    id uuid primary key default gen_random_uuid(),
    race_event_id uuid not null references public.race_events(id) on delete cascade,
    participant_id uuid not null references public.participants(id),
    points numeric not null,
    scoring_rule_version text not null,
    calculated_at timestamptz not null default now(),
    unique (race_event_id, participant_id)
);

-- ============================================================
-- F1 fantasy draft
-- ============================================================

create table public.f1_drivers (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),
    full_name text not null,
    team_name text not null,
    is_reserve boolean not null default false,
    is_active boolean not null default true,
    unique (season_id, full_name)
);

comment on table public.f1_drivers is
    'The draftable pool for a season. Deliberately not assumed to match '
    'league size exactly — pool size vs. picks-needed is validated at '
    'draft time, not hard-coded.';

create table public.draft_picks (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),
    participant_id uuid not null references public.participants(id),
    f1_driver_id uuid not null references public.f1_drivers(id),
    pick_number int not null,           -- overall pick order, for draft history/replay
    round_number int not null,
    picked_at timestamptz not null default now(),
    unique (season_id, f1_driver_id),   -- a driver can only be drafted once per season
    unique (season_id, participant_id, round_number)
);

-- Real-world F1 race results, feeding fantasy scoring. Data source TBD
-- (Jolpica-F1 API is the free Ergast-compatible option) — this table is
-- the adapter boundary: however results arrive, they land here in a
-- consistent shape before fantasy scoring touches them.
create table public.f1_race_results (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),
    round_number int not null,
    race_name text not null,
    is_sprint boolean not null default false,
    f1_driver_id uuid not null references public.f1_drivers(id),
    finish_position int,
    status text,                        -- Finished / DNF / DSQ / etc.
    points numeric,                     -- official F1 points for this result
    fastest_lap boolean not null default false,
    imported_at timestamptz not null default now(),
    unique (season_id, round_number, is_sprint, f1_driver_id)
);

create table public.fantasy_points_awarded (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),
    participant_id uuid not null references public.participants(id),
    round_number int not null,
    points numeric not null,
    scoring_rule_version text not null,
    calculated_at timestamptz not null default now(),
    unique (season_id, participant_id, round_number)
);

-- ============================================================
-- Constructors' Championship
-- ============================================================

create table public.constructors (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),
    name text not null                  -- e.g. "McLaren"
);

-- Join table rather than a fixed 2-column pairing on `constructors` —
-- league size (11) doesn't split evenly into pairs, so team size is
-- validated at the application/admin layer, not constrained to exactly 2
-- in the schema. Once the pairing rule is decided, add a check there.
create table public.constructor_members (
    constructor_id uuid not null references public.constructors(id) on delete cascade,
    participant_id uuid not null references public.participants(id),
    primary key (constructor_id, participant_id),
    unique (constructor_id, participant_id)
);

-- ============================================================
-- Scoring configuration
-- ============================================================

-- Configurable position -> points mapping, versioned so historical
-- standings remain reproducible even after rules change mid-season.
create table public.scoring_rules (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references public.seasons(id),
    rule_type text not null,            -- 'sim_racing' | 'fantasy_f1'
    version text not null,
    position int not null,
    points numeric not null,
    is_active boolean not null default true,
    unique (season_id, rule_type, version, position)
);

-- ============================================================
-- Row Level Security (enabled, policies TBD once auth roles are finalized)
-- ============================================================

alter table public.participants enable row level security;
alter table public.seasons enable row level security;
alter table public.race_events enable row level security;
alter table public.race_results enable row level security;
alter table public.sim_points_awarded enable row level security;
alter table public.f1_drivers enable row level security;
alter table public.draft_picks enable row level security;
alter table public.f1_race_results enable row level security;
alter table public.fantasy_points_awarded enable row level security;
alter table public.constructors enable row level security;
alter table public.constructor_members enable row level security;
alter table public.scoring_rules enable row level security;

-- Policies intentionally not defined yet — public vs. private page split
-- (Section 11 of the design doc) is still open. RLS is enabled by default
-- (safe default = no access) so nothing is accidentally exposed before
-- policies are written.
