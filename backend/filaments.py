"""Request catalog. Quoting is enabled only after matching profiles and rates exist."""

TYPES = ("PLA", "PETG", "ABS", "ASA", "TPU")


def catalog():
    from backend import integrations

    profiles = integrations.public_profiles()
    return [
        dict(
            material=m,
            requestable=True,
            quoting_enabled=m == "PLA" and any(p["available"] for p in profiles),
            status="configured"
            if m == "PLA" and any(p["available"] for p in profiles)
            else "awaiting_profiles_and_rates",
            profile_ids=[p["id"] for p in profiles if p["available"]]
            if m == "PLA"
            else [],
            required=[]
            if m == "PLA"
            else [
                "Saved Bambu Studio reference project per compatible printer/nozzle",
                "Material cost per kg",
                "Verified sample slice and material-specific scheduling compatibility",
            ],
        )
        for m in TYPES
    ]
