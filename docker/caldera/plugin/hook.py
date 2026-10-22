from app.utility.base_world import BaseWorld

name = 'mrhOTshOT'
description = ('mrhOTshOT lab OT pack: Modbus abilities tuned to the containerized '
              'heating PLC (ENCO ENC-12X, unit 11), a fact source pre-pointed at '
              'plc-heating, and a FrostyGoop-style sabotage adversary.')
address = None
access = BaseWorld.Access.RED


async def enable(services):
    # Data-only plugin: Caldera auto-loads data/{abilities,adversaries,sources}
    # for any enabled plugin. Nothing to wire up here.
    pass
