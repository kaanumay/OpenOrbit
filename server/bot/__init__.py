"""Bots: server-side pilots that behave like real players (belgeler/BOTLAR.md).

personality  traits, archetypes, mood, name generator, roster
catalog      ship/laser/generator/drone catalog, power score, map difficulty and income
state        Bot: persistent record (Profile format) + temporary fields
agent_tools  the bot's actions (the decision engine and the LLM call the same tools)
brain        utility AI (goals/ modules)
abstract_sim simulation of bots that are not on the player's map
ship         the ship of bots on the player's map (world.World.npcs)
manager      loading the package, scheduler, record
"""
