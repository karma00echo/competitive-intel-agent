"""Application-layer reads for the pure cross-product matrix builder."""

from dataclasses import replace

from competitive_intel.domain.competitive_matrix import build_matrix, decode


class CompetitiveMatrixService:
    def __init__(self, persistence):
        self.persistence = persistence

    def build(self, task, products):
        with self.persistence.transaction() as session:
            rows = {p.run_id: self.persistence.fact_observations.list_for_matrix(session, p.run_id)
                    for p in products if p.run_id is not None}
            checked = []
            for product in products:
                conflicts = set(product.conflicted_fact_keys)
                run = self.persistence.agent_runs.get(session, product.run_id) if product.run_id else None
                if run:
                    for call in self.persistence.tool_calls.list_for_run(session, product.run_id):
                        audit = decode(call.get("output_summary")) or {}
                        pages = audit.get("provider_calls", []) + [audit]
                        for page in pages:
                            conflicts.update(c["canonical_identity"] for c in page.get("identity_conflicts", []))
                checked.append(replace(product, conflicted_fact_keys=tuple(sorted(conflicts)),
                    status=product.status if run and run["status"] == "COMPLETED" else "PARTIAL"))
        return build_matrix(task, checked, rows)
