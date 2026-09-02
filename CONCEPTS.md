# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## The store

### Task
One closing period as the operator names it: a title, an optional period, and everything produced for it. A Task owns its Windows, the Sessions recorded against it, and its Deliverable Versions; a Session belongs to exactly one Task and is refused by any other.

### Window
One caliber lock of the books imported for a Task. A re-import does not change a Window; it opens a successor, and follow-ups asked of the earlier brief stay on the earlier Window. A Task is therefore a chain of Windows, each answering for its own inputs.

### Deliverable Version
One filed copy of a document a Window produced, kept by the bytes' digest and never rewritten. Kinds are the brief, the workpaper, and an export such as a workbook. A re-render that produces identical bytes files nothing; a changed document files a new version with the cause that changed it.

### Workbook
A Deliverable Version written as a spreadsheet from the locked catalog, one sheet each for the period, the conclusions, the workpaper, and the external references. It is the form the close is delivered in; a person sorts and pivots it in their own spreadsheet software.

## Seats and the fence

### Seat
Which kind of work a conversation is opened for, and so which tools it can reach: the authoring seat writes a method, the close seat runs a period, the follow-up seat may only query the locked catalog. The button that opens the conversation decides the seat; nothing inside the conversation can widen it.

### Fence
The boundary on what a figure may claim and what a seat can reach. A figure must say where it came from, the locked catalog or an external reference; a seat is denied every capability that would let it read around the catalog. The fence is structural, not a rule the model is asked to follow.

### Companion
A third-party bundle staged beside the kit's own bundle and named in the harness profile, with the tools it must not expose to the close seat, the switches it may not run without, and the hosts it may reach declared up front. The Office companion is the spreadsheet plugin; the file-upload companion is the input drop.

## The window's surfaces

### Pane
An embedded page shown as a native view in window coordinates under this app's own strips: the harness conversation, the data reader, or a Workbook Preview. A Pane is shown or hidden by being given a rectangle or none, and taking it down ends its page, not only its view.

### Strip
The app's own bar between the header and a Pane, saying what the Pane is: which Task a conversation writes to, which data lease is held, which Workbook is being looked at. A Strip is the only place a control can be drawn over a Pane, and what it names is what is running.

### Workbook Preview
A look at one Workbook inside the window, in the Office companion's viewer, without leaving the app or opening the filed copy. The viewer needs a server and a container of its own, so a preview is a Gateway, a Scratch Container, and a Pane, all of which exist only while the Strip names that version; leaving the version takes all three down. Nothing typed into it reaches the filed Workbook, and no model can reach the Gateway.

### Scratch Container
The companion viewer's own file format holding a copy of one Workbook, derived from the filed bytes on each open and deleted on close. It lives inside the Task's own artifacts, in a directory of its own, because the Gateway refuses to serve a container outside or at the root it is fenced to.

### Gateway
The Office companion's local collaboration server that the viewer talks to. The app spawns one per Workbook Preview, fenced to the Task's artifacts and alive only while the preview is; the companion's own Gateway, used by the authoring seat's tools, is a different process the app neither fences nor uses.

## Flagged ambiguities

- "Preview" had been used for both the in-window look at a Workbook and the merge preview inside the companion's viewer. Here it means the Workbook Preview; the companion's merge preview is not a concept of this project.
- "Workspace" and "artifacts" are two per-Task trees. The workspace is where a conversation stands; the artifacts are where Deliverable Versions are filed. The Gateway is fenced to the second, never the first.
