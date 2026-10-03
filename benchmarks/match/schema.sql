pragma foreign_keys = on;

create table dataset_meta(key text primary key, value text not null);

create table reference_phases(
    phase_id text primary key,
    source text not null check(source = 'COD'),
    entry_id text not null,
    formula text not null,
    formula_key text not null,
    name text not null,
    spacegroup text not null,
    family_id text not null,
    unique(source, entry_id)
);

create table reference_peaks(
    phase_id text not null references reference_phases(phase_id) on delete cascade,
    peak_index integer not null,
    two_theta real not null,
    d real,
    intensity real not null,
    h integer,
    k integer,
    l integer,
    multiplicity integer,
    primary key(phase_id, peak_index)
);

create table experimental_patterns(
    pattern_id text primary key,
    source text not null,
    source_id text not null,
    source_url text not null default '',
    sha256 text not null default '',
    citation text not null default '',
    radiation text not null default '',
    x_blob blob not null,
    y_blob blob not null,
    point_count integer not null
);

create table experimental_targets(
    pattern_id text not null references experimental_patterns(pattern_id) on delete cascade,
    family_id text not null,
    role text not null default 'primary',
    primary key(pattern_id, family_id)
);

create table phase_categories(
    phase_id text primary key references reference_phases(phase_id) on delete cascade,
    category text not null,
    rule text not null
);

create table split_assignments(
    family_id text primary key,
    split text not null check(split in ('train', 'validation', 'test'))
);

create table scenario_definitions(
    scenario_id text primary key,
    split text not null,
    seed integer not null,
    parameters_json text not null
);

create table scenario_components(
    scenario_id text not null references scenario_definitions(scenario_id) on delete cascade,
    phase_id text not null references reference_phases(phase_id),
    fraction real not null,
    component_order integer not null,
    primary key(scenario_id, component_order)
);
