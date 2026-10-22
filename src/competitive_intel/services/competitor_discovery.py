"""Evidence-based competitor discovery; no historical facts or baselines are changed."""

from dataclasses import asdict
from hashlib import sha256
import re

from bs4 import BeautifulSoup

from competitive_intel.domain.content_cleaner import clean_page
from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.domain.official_domain import aggregate_domain_evidence, select_official_domain
from competitive_intel.domain.official_validation import validate_official_source
from competitive_intel.domain.search import SearchIntent, SearchRequest
from competitive_intel.domain.sources import PageEvidence, VerificationStatus
from competitive_intel.domain.task_budget import BudgetExhausted
from competitive_intel.domain.urls import normalize_url, registrable_domain
from competitive_intel.domain.webpage import CleanPageRequest, FetchPageRequest, FetchStatus
from competitive_intel.infrastructure.search.search_web import search_web


def key(name):
    return normalize_competitor_name(name).normalized_name


def nomination_name(value):
    """Conservative page-title/link label parsing, never a product lookup list."""
    value = re.split(r"\s+[|:：–—-]\s*|[|｜：]", value)[0].strip()
    if not 2 <= len(value) <= 60 or len(value.split()) > 5:
        return None
    if re.search(r"\d|alternatives?|competitors?|best|review|pricing|official|官网|替代|竞品|排行|推荐|登录|click|learn|sign in|read more", value, re.I):
        return None
    if not re.fullmatch(r"[\w .+&-]+", value):
        return None
    return value


class CompetitorDiscoveryService:
    """Caller supplies one task context shared with understanding and future research."""

    def __init__(self, context, search, fetcher, evaluator):
        self.context, self.search, self.fetcher, self.evaluator = context, search, fetcher, evaluator
        self.pages = {}  # Task-local successful evidence only; no stale/failed replay.
        self.searches = []
        self.issues = []
        self.interpretation_audit = None

    def _search(self, query, intent=SearchIntent.OFFICIAL_SITE):
        response = search_web(self.search, SearchRequest(query, intent, language="zh", limit=8))
        self.searches.append({"query": query, "provider": response.provider,
                              "error_code": response.error_code,
                              "results": [asdict(r) for r in response.results[:8]]})
        if not response.ok:
            raise RuntimeError("SEARCH_PROVIDER_FAILED")
        return response.results[:8]

    def _page(self, url):
        url = normalize_url(url)
        if url in self.pages:
            return self.pages[url]
        fetched = self.fetcher.fetch(FetchPageRequest(url))
        if fetched.fetch_status != FetchStatus.SUCCESS or not fetched.raw_html:
            self.issues.append({"code": "PAGE_UNAVAILABLE", "url": url,
                                "fetch_status": fetched.fetch_status.value})
            return None
        final = normalize_url(fetched.final_url or url)
        cleaned = clean_page(CleanPageRequest(fetched.raw_html, final))
        text = cleaned.clean_content[:12000]
        if not text.strip():
            return None
        evidence = {"url": final, "requested_url": url, "title": cleaned.page_title or fetched.page_title,
                    "content": text, "content_sha256": sha256(text.encode()).hexdigest(),
                    "collected_at": fetched.fetched_at.isoformat(), "raw_html": fetched.raw_html}
        self.pages[url] = evidence
        return evidence

    def _identity(self, name):
        identity = normalize_competitor_name(name)
        results = list(self._search(f'"{name}" official website'))
        results += list(self._search(f'"{name}" product features', SearchIntent.FEATURES))
        representatives = {}
        for result in results:
            try:
                validation = validate_official_source(identity, result)
                if validation.verification_status != VerificationStatus.REJECTED:
                    representatives.setdefault(registrable_domain(result.url), result)
            except ValueError:
                continue
        pages, validations = {}, []
        # Reuse the existing domain scoring/margin policy. Inspect a bounded set
        # of promising domains, but retain all search candidates in aggregation.
        # Unfetched search hits alone cannot establish official identity.
        if len(representatives) > 2:
            self.issues.append({"code": "IDENTITY_VALIDATION_LIMIT", "name": name,
                                "uncertainty": "Only two candidate domains were fetched."})
        ranked = sorted(representatives.values(), key=lambda r: (
            -sum(key(name) in key(item.title + " " + item.snippet) for item in results
                 if registrable_domain(item.url) == registrable_domain(r.url)),
            r.rank))
        for result in ranked[:2]:
            page = self._page(result.url)
            if page:
                evidence = PageEvidence(page["url"], page["title"], page["content"], page["raw_html"], FetchStatus.SUCCESS)
                pages[normalize_url(result.url)] = evidence
                validations.append(validate_official_source(identity, result, evidence))
        domains = aggregate_domain_evidence(identity, tuple(results), tuple(validations), pages)
        domain, reason = select_official_domain(domains)
        valid = [v for v in validations if v.verification_status == VerificationStatus.VERIFIED
                 and registrable_domain(v.normalized_url) == domain]
        if not domain or not valid:
            self.issues.append({"code": "IDENTITY_UNRESOLVED", "name": name, "reason": reason})
            return None
        selected = valid[0]
        page = self.pages[normalize_url(selected.candidate_url)]
        if registrable_domain(page["url"]) != domain:
            return None
        return {"name": name, "domain": domain, "identity_confidence": selected.confidence,
                "identity_reason": reason, **{k: v for k, v in page.items() if k != "raw_html"}}

    def _nominate(self, target):
        results = self._search(f'"{target}" alternatives competitors')
        proposals, seen = [], {key(target)}

        def add(label, source):
            name = nomination_name(label)
            if name and key(name) not in seen:
                seen.add(key(name))
                proposals.append({"name": name, "discovered_from": source})

        for result in results:
            add(result.title, {"url": result.url, "query": result.query, "title": result.title,
                               "kind": "search_lead_not_identity_proof"})
        # Articles can nominate names through labelled external links. They never
        # prove ownership or relevance; each nominee still requires official pages.
        for result in results[:2]:
            if len(proposals) >= 3:
                break
            page = self._page(result.url)
            if not page:
                continue
            for anchor in BeautifulSoup(page["raw_html"], "html.parser").find_all("a", href=True)[:80]:
                try:
                    link = normalize_url(str(anchor["href"]), base_url=page["url"])
                    if registrable_domain(link) == registrable_domain(page["url"]):
                        continue
                except ValueError:
                    continue
                add(anchor.get_text(" ", strip=True), {"url": page["url"], "linked_url": link,
                      "content_sha256": page["content_sha256"], "collected_at": page["collected_at"],
                      "kind": "external_link_lead_not_identity_proof"})
                if len(proposals) >= 3:
                    break
        return proposals[:3]

    @staticmethod
    def _grounded(item, target, candidate):
        use = item.shared_use.casefold().strip()
        if use in {"ai", "人工智能", "智能", "软件", "产品", "工具", "software", "platform", "assistant",
                   "for teams", "teams", "users", "business", "企业", "用户", "团队"}:
            return False
        for quote, product in ((item.target_quote, target), (item.candidate_quote, candidate)):
            if quote not in product["content"] or key(product["name"]) not in key(quote) or use not in quote.casefold():
                return False
            # A comparison/list mentioning both brands is not an own-product claim.
            subject = re.escape(product["name"])
            if not re.match(r"^" + subject + r"(?:\s+(?:provides|offers|helps|supports|enables|is\b)|(?:提供|支持|帮助|用于|是一|是一个))", quote, re.I):
                return False
            if re.search(r"\b(not|unlike|without|instead|versus|vs)\b|不支持|不能|没有|相比|不同于|而非", quote, re.I):
                return False
        return len(use) >= (2 if re.search(r"[\u4e00-\u9fff]", use) else 5)

    def discover(self, task):
        result = {"phase": "competitor_discovery", "status": "PARTIAL", "task": task.model_dump(),
                  "target": None, "candidates": [], "selected": [], "issues": self.issues,
                  "report_id": None, "analysis_complete": False}
        if task.competitors:
            result["selected"] = list(task.competitors)  # User scope survives all failures.
            result["candidates"] = [{"name": n, "selection": "USER_SPECIFIED", "status": "UNVERIFIED",
                                     "uncertainty": "Identity and relevance have not been verified."} for n in task.competitors]
        try:
            if task.status != "READY":
                result["status"] = task.status
                return result
            target = self._identity(task.target)
            result["target"] = target
            if not target:
                result["status"] = "NEEDS_CLARIFICATION"
                self.issues.append({"code": "TARGET_UNRESOLVED", "question": "请补充产品所属公司或用途，以消除身份歧义。"})
                return result
            if not task.discover_competitors and not task.competitors:
                result["status"] = "READY"
                return result
            proposals = ([{"name": n, "discovered_from": {"kind": "user"}} for n in task.competitors]
                         if task.competitors else self._nominate(task.target))
            candidates = result["candidates"] if task.competitors else []
            result["candidates"] = candidates
            verified, domains = [], {target["domain"]}
            for index, proposal in enumerate(proposals):
                candidate = candidates[index] if task.competitors else dict(proposal, status="UNVERIFIED")
                if not task.competitors:
                    candidates.append(candidate)
                identity = self._identity(proposal["name"])
                if identity is None:
                    candidate["uncertainty"] = "Insufficient or ambiguous official identity evidence."
                    continue
                candidate["identity"] = identity
                if identity["domain"] in domains:
                    candidate.update(status="AMBIGUOUS", uncertainty="Shared domain may be an alias or another product; not auto-selected.")
                    continue
                domains.add(identity["domain"])
                candidate["status"] = "IDENTITY_VERIFIED"
                verified.append(candidate)
            if task.competitors:
                result["status"] = "READY" if len(verified) == len(task.competitors) else "PARTIAL"
                for candidate in candidates:
                    candidate["uncertainty"] = candidate.get("uncertainty", "User-selected scope; competitive relevance is not inferred here.")
                return result
            if not verified:
                self.issues.append({"code": "NO_VERIFIED_CANDIDATES"})
                return result
            evaluated = self.evaluator.evaluate(target, [c["identity"] for c in verified])
            by_name = {key(c["name"]): c for c in verified}
            seen = set()
            for item in evaluated.candidates:
                name = key(item.name)
                candidate = by_name.get(name)
                if candidate is None or name in seen:
                    self.issues.append({"code": "UNKNOWN_OR_DUPLICATE_EVALUATION_NAME"})
                    continue
                seen.add(name)
                if not self._grounded(item, target, candidate["identity"]):
                    self.issues.append({"code": "RELEVANCE_EVIDENCE_REJECTED", "name": item.name})
                    continue
                candidate.update(status="SUPPORTED_CANDIDATE", relevance=item.model_dump(),
                                 selection="EVIDENCE_BASED_INFERENCE", confidence="moderate",
                                 uncertainty="Overlapping use supports candidacy, not proven direct competition or market ranking.")
                if len(result["selected"]) < 2:
                    result["selected"].append(candidate["name"])
            result["status"] = "READY" if len(result["selected"]) == 2 and not self.issues else "PARTIAL"
            if len(result["selected"]) < 2:
                self.issues.append({"code": "INSUFFICIENT_SUPPORTED_CANDIDATES"})
        except BudgetExhausted as exc:
            self.issues.append({"code": "TASK_BUDGET_EXHAUSTED", "resource": exc.resource})
            result["status"] = "PARTIAL"
        except Exception as exc:
            self.issues.append({"code": "DISCOVERY_PROVIDER_FAILED", "type": type(exc).__name__})
            result["status"] = "PARTIAL"
        finally:
            result["budget"] = self.context.budget.snapshot()
            result["search_audit"] = self.searches
            result["evidence"] = [{k: v for k, v in p.items() if k != "raw_html"} for p in self.pages.values()]
            result["evaluation_usage"] = getattr(self.evaluator, "usage", None)
            result["interpretation_audit"] = self.interpretation_audit
            result["research_policy"] = self.context.audit_policy()
            result["evaluation_policy"] = "candidate-relevance-v1"
            result["providers"] = {"search_provider": self.search.name,
                                   "fetch_mode": self.context.audit_policy()["transport_mode"],
                                   "agent_provider": "controlled", "fact_provider": "not_run"}
        return result
