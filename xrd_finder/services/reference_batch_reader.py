"""Small coherent prepared-reference snapshots, released before scoring."""
from concurrent.futures import CancelledError
import sqlite3
from xrd_finder.services.normalized_reflections import ordered_card_query

REFERENCE_BATCH_SIZE = 16
REFERENCE_COLUMNS = ('d','two_theta','intensity','norm_intensity','raw_intensity',
                     'h','k','l','multiplicity','intrinsic_intensity','intensity_origin')


def read_reference_batch(connection, keys, *, columns, classify, convert, cancelled=None):
    """Return key -> converted value/exception; DB failures/cancellation are fatal.

    classify(key, metadata, connection) returns None for ready cards, otherwise
    their unavailable result. convert consumes ordered typed rows for one card.
    """
    keys = list(dict.fromkeys(keys))
    if len(keys)>REFERENCE_BATCH_SIZE:
        raise ValueError('Prepared reference batch is too large')
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Prepared reference loading cancelled')
    check()
    if not keys:
        return {}
    if connection.in_transaction:
        raise RuntimeError('Prepared batch requires its own read snapshot')
    results,ready,metadata = {},[],{}
    connection.set_progress_handler(lambda:int(cancelled is not None and cancelled()),5000)
    try:
        connection.execute('BEGIN')
        marks = ','.join('(?,?)' for _ in keys)
        rows = connection.execute(
            f'with requested(source,entry_id) as (values {marks}) '
            'select p.source,p.entry_id,p.derived_version,substr(p.peaks_json,1,1024) as first_lines '
            'from requested r join phases p on p.source=r.source and p.entry_id=r.entry_id',
            [v for key in keys for v in key])
        metadata = {(r['source'],r['entry_id']):r for r in rows}
        for key in keys:
            check()
            try:
                result = classify(key,metadata.get(key),connection)
            except (sqlite3.DatabaseError,CancelledError):
                raise
            except Exception as error:
                result = error
            if result is None:
                ready.append(key)
            else:
                results[key] = result
        if ready:
            query = ordered_card_query(connection,columns)
            def checked_rows(group):
                for i,row in enumerate(group):
                    if i%256==0:
                        check()
                    yield row
            # Batch metadata and transaction ownership, then stream each card
            # directly from its ordered primary key. Grouped reflection reads
            # added sorting/row-splitting costs on dense real cards.
            for key in ready:
                cursor = connection.execute(query,key)
                check()
                try:
                    results[key] = convert(key,metadata[key],checked_rows(cursor))
                except (sqlite3.DatabaseError,CancelledError):
                    raise
                except Exception as error:
                    results[key] = error
                finally:
                    cursor.close()
        check()
        return results
    except sqlite3.OperationalError as error:
        check()
        raise
    finally:
        connection.set_progress_handler(None,0)
        connection.rollback()
