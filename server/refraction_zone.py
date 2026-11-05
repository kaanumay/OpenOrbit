"""R-Zone (Refractions) standby, as the real server answers (record 20261025_152841_gercek, t=323.875..324.848): RzoneSignUpRequest ->
RzoneStatusCommand {RzoneQueueingStatusModule}; RzoneCancelSignUpRequest -> {RzoneRegistrationStatusModule}. The login and every map's
ready bundle carry the Registration state (the template's RzoneStatusCommand). The client's handler and window are alive
(RzoneStatusCommandHandler -> RZoneModel -> UIRefractions), but the real server keeps the menu item hidden in every record
(player_profile.HIDDEN_WINDOWS) and no match ever came: the cross-server mode is not built (belgeler/arastirma/PVP_MODLARI.md section 5)."""


def status(module):
    return ('RzoneStatusCommand', {'statusType': {'_': module}})


class RefractionZone:
    REQUESTS = ('RzoneSignUpRequest', 'RzoneCancelSignUpRequest', 'RzoneConfirmRequest', 'RzoneCancelRequest', 'RzoneLeaveMapRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.log = profile, log
        self.queued = False

    def handle(self, name, f):
        if name == 'RzoneSignUpRequest':
            self.queued = True
            return [status('RzoneQueueingStatusModule')]
        self.queued = False                     # cancel, a refused / stale confirmation, leaving: back to the registration state
        return [status('RzoneRegistrationStatusModule')]
