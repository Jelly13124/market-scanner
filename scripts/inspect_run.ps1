param([string]$RunId)
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8001/pipeline/runs/$RunId"
foreach ($t in $r.agent_decisions.PSObject.Properties.Name) {
    $d = $r.agent_decisions.$t
    Write-Output ""
    Write-Output ("### {0}  action={1} qty={2} conf={3}" -f $t, $d.action, $d.quantity, $d.confidence)
    Write-Output ("  PM: {0}" -f $d.reasoning)

    # fundamentals: check ROE/margin scale
    $f = $r.analyst_signals.fundamentals_analyst_agent.$t
    if ($f) {
        Write-Output ("  [fundamentals] signal={0} conf={1}" -f $f.signal, $f.confidence)
        foreach ($k in $f.reasoning.PSObject.Properties.Name) {
            Write-Output ("    {0} -> {1}" -f $k, $f.reasoning.$k.details)
        }
    }

    # technicals: check momentum_6m and hurst
    $tech = $r.analyst_signals.technical_analyst_agent.$t
    if ($tech) {
        $mom = $tech.reasoning.momentum.metrics
        $h = $tech.reasoning.statistical_arbitrage.metrics
        Write-Output ("  [technicals] signal={0} mom_1m={1:F3} mom_3m={2:F3} mom_6m={3:F3} hurst={4:F3}" -f `
            $tech.signal, $mom.momentum_1m, $mom.momentum_3m, $mom.momentum_6m, $h.hurst_exponent)
    }

    # valuation: check method gaps
    $v = $r.analyst_signals.valuation_analyst_agent.$t
    if ($v) {
        Write-Output ("  [valuation] signal={0} conf={1}" -f $v.signal, $v.confidence)
        foreach ($k in $v.reasoning.PSObject.Properties.Name) {
            $det = $v.reasoning.$k.details
            if ($det) {
                if ($det.Length -gt 220) { $det = $det.Substring(0,220) + "..." }
                Write-Output ("    {0} -> {1}" -f $k, $det)
            }
        }
    }

    # risk management: verify conf is null/missing (so frontend hides it)
    $rm = $r.analyst_signals.risk_management_agent.$t
    if ($rm) {
        Write-Output ("  [risk_management] signal={0} conf={1}" -f $rm.signal, $rm.confidence)
    }
}
