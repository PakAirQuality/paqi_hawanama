"""
ICIMOD Air Quality Watch (pakistan.smog.icimod.org) adapter — shadow provider.

ICIMOD republishes the EPCCD Punjab ground stations through an open API. This
adapter polls that feed hourly as an *independent* source (`providers.code =
'icimod'`, `readings.source = 'icimod'`, shadow stations `ic_…` with
`active=false`) so its coverage and timing can be measured against the Punjab
EPA feed before any value is used to fill a Punjab gap. Nothing here is shown
on the map, exported or counted.
"""
