# Assistant tool discovery and scheduling

Capability answers inspect the tool bundles actually passed to the supervisor,
productivity, Mac, weather, and diagnostics agents, plus the direct knowledge tool.
Installed UI apps are read from their manifests. An installed app is not proof of
data access: Calendar/Reminders use native EventKit helpers; YouTube currently has
assistant window open/close controls, not video-search or selection tools.

Add new tools to the corresponding agent's exported tool bundle. Optional tool
metadata `capability` supplies a short spoken label; otherwise the tool name is
used. The registry automatically includes new bundle entries and their schemas.
New agent types must also be registered in `capability_snapshot`.

Calendar and reminder tools reuse the desktop's native helpers and permissions.
The assistant does not request permission automatically or claim a failed read
means an empty schedule. Set `DARWIN_TIMEZONE` to an IANA timezone if the system
timezone is unsuitable. Relative dates use local calendar-day boundaries.

Event creation requires a title and offset-aware start/end timestamps. Missing
dates, times, or duration produce clarification, never a write. Productivity
conversations are checkpointed per runtime session so supplied details carry
across follow-ups. Event deletion removes one exact occurrence and uses DARWIN's
existing confirmation flow. Denial does not reach the native helper.

Day overviews mention at most two event titles and group remaining commitments.
Ask for more detail to use the full schedule through the agent. Date overview
summaries deliberately avoid reading every note, calendar name, or identifier.

Restart the Electron/backend process after changing registered tools. Renderer
hot reload does not reload already constructed Python agent graphs.

## Global progress acknowledgements

The runtime acknowledges tool-backed requests once with a non-final response.
Recognized lookups get immediate domain wording; any newly registered graph tool
gets acknowledgement on its first tool activity. Slow unfamiliar requests receive
a delayed fallback after one second, while fast ordinary replies stay quiet.
Weather uses the same deduplication path. Cancelled/completed requests cannot emit
late progress. Acknowledgement describes work, not completion or permission to write.

Desktop fetches run in worker threads while acknowledgements are delivered/spoken.
Wake-word and manual voice input speak progress; terminal clients subscribe to it
and serialize progress audio before final response audio. Constructor options
`enable_acknowledgements=False` and `acknowledgement_delay` allow client tuning.
