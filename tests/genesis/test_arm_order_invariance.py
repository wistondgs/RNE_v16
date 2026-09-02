from tests.genesis._m5_helpers import run
def test_scientific_summary_is_order_invariant_while_trace_records_order():
 one,_=run(order=("control","treatment","placebo"));two,_=run(order=("placebo","control","treatment"));assert one.trace.trace_hash!=two.trace.trace_hash;assert one.summary.effects==two.summary.effects;assert one.cfi.status==two.cfi.status
