# Antigravity foreground route

Gateway accepts an explicit `matrix antigravity run JSON` owner command when
`interaction.antigravity_foreground` is selected. It uses the same original
selection, Matrix body verification, journal, capacity and response path as
Claude and Goose. `matrix antigravity status EVENT_ID` reads the retained
attempt. An original already admitted by any foreground engine keeps that
engine and outcome, including across restarts.

A configured worker must speak `daimon-gateway.antigravity-turn/v1` over the
existing JSON lines worker protocol. Its start frame carries Gateway's selected
session UUID. Before submitting the original to Antigravity, the worker must
verify the effective tool catalog and receiving body and return that exact
UUID as `nativeSessionId` in `prepare_submission`. Gateway requires the explicit
ID and commits it together with provider exposure before releasing the worker.
An absent or different native ID prevents submission. Loss after the commit
retains uncertainty.

The Gateway route currently has a synthetic worker fixture. Leave the
configuration unset until a worker has passed the real SDK and receiving
checks. The maintained qualification and its limits are recorded in
[Matrix #497](https://github.com/AlterMundi/daimon-matrix/issues/497).
