from magnacoda.findings.models import ScanMeta, ScanReport


def fake_run(seen: list):
    """Stands in for magnacoda's run_scan: records the config and returns an empty report."""

    def fake_run_scan(config, *, consent_given=False):
        seen.append(config)
        meta = ScanMeta(
            tool_version="0",
            axe_core_version="0",
            wcag_version="2.2",
            wcag_level="AA",
            ai_tier="off",
            fixes_tier="template",
            color_scheme=config.color_scheme,
            screen=config.screen,
            stability_settled=True,
            stability_elapsed_ms=0,
            stability_reason="quiescent",
        )
        return ScanReport(url=config.url, meta=meta, findings=[])

    return fake_run_scan
