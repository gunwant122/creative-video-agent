"""Export the timeline to OpenTimelineIO so an editor can finish it in Premiere / Resolve / FCP."""
from __future__ import annotations

from cva.vv.layout import layout
from cva.vv.project import Project


def export(p: Project, out: str) -> str:
    import opentimelineio as otio  # optional dependency: pip install cva[otio]

    lay = layout(p)
    F = lay["fps"]
    tl = otio.schema.Timeline(name="episode")
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    tl.tracks.append(track)
    for it in lay["items"]:
        src = p.source(it["src"])
        if it["tin"]["type"] == "dissolve":
            d = it["tin"]["frames"]
            track.append(otio.schema.Transition(
                transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                in_offset=otio.opentime.RationalTime(it["pre"], F),
                out_offset=otio.opentime.RationalTime(d - it["pre"], F)))
        ref = otio.schema.ExternalReference(target_url=str(p.abspath(src["path"])))
        track.append(otio.schema.Clip(
            name=it["id"], media_reference=ref,
            source_range=otio.opentime.TimeRange(otio.opentime.RationalTime(it["in"], F),
                                                 otio.opentime.RationalTime(it["L"], F))))
    path = p.abspath(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(tl, str(path))
    return str(path)
