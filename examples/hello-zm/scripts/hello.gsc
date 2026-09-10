// hello-zm: prints once when the map starts. Used by the toolkit's first-run qualification.
#include maps\mp\_utility;
#include common_scripts\utility;

main()
{
    level thread hello_on_start();
}

hello_on_start()
{
    flag_wait( "initial_blackscreen_passed" );
    iprintln( "^2hello-zm loaded through the Plutonium Agent Toolkit" );
}
