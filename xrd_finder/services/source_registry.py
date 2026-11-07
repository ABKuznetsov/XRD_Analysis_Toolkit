"""Common eligibility rules for built-in and user-configured CIF sources."""
import re
from contextlib import closing

STRUCTURE_SOURCES = frozenset({'COD','USER','CCDC','MP','AFLOW','OQMD','COREMOF'})
ORGANIC_FRAMEWORK_SOURCES = frozenset({'COREMOF','LIB_434F46001000','LIB_514D4F460018'})


def organic_material_sql(alias='p'):
    """Indexed class filter; known framework sources may omit hydrogen sites."""
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',alias):
        raise ValueError('Invalid internal SQL alias')
    carbon=(f"exists(select 1 from phase_elements e where e.source={alias}.source "
            f"and e.entry_id={alias}.entry_id and e.element='C')")
    hydrogen=(f"exists(select 1 from phase_elements e where e.source={alias}.source "
              f"and e.entry_id={alias}.entry_id and e.element='H')")
    known=','.join("'"+source+"'" for source in sorted(ORGANIC_FRAMEWORK_SOURCES))
    return f'({carbon} and ({hydrogen} or {alias}.source in ({known})))'


def is_custom_source(source):
    return bool(re.fullmatch(r'LIB_[0-9A-F]{12}', str(source)))


def is_structure_source(source):
    return source in STRUCTURE_SOURCES or is_custom_source(source)


def saved_custom_sources(cache):
    with closing(cache._connect()) as connection:
        return [row[0] for row in connection.execute("select distinct source from phases where source like 'LIB_%'")
                if is_custom_source(row[0])]
