// hello-iw5: prints to each player once they spawn. The IW5 counterpart of hello-zm.
// Plutonium IW5 compiles this source itself; the toolkit packs the text and uses gsc-tool -g iw5
// only as a dry-run syntax check. Uses only engine builtins so no include file is needed.

main()
{
    level thread on_player_connect();
}

init()
{
}

on_player_connect()
{
    for ( ;; )
    {
        level waittill( "connected", player );
        player thread on_player_spawned();
    }
}

on_player_spawned()
{
    self waittill( "spawned_player" );
    self iprintln( "^2hello-iw5 loaded through the Plutonium Agent Toolkit" );
}
