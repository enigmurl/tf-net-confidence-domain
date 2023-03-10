import torch


class HammerSchedule:
    def __init__(self, lorris, lorris_buffer, lorris_decay, hammer, hammer_buffer, hammer_decay):
        self.lorris = lorris
        self.lorris_buffer = lorris_buffer
        self.lorris_decay = lorris_decay

        self.hammer = hammer
        self.hammer_buffer = hammer_buffer
        self.hammer_decay = hammer_decay

        self.step_num = 0

    def _fallof(self, decay):
        return 2 ** (-self.step_num * decay)

    def hammer_loss(self, true_point, predicted_max):
        buffer = self.hammer_buffer * self._fallof(self.hammer_decay)
        scalar = self.hammer * self._fallof(self.hammer_decay)

        diff = torch.sqrt(buffer + torch.relu(true_point - predicted_max + buffer))
        t1 = torch.square(torch.mean(diff)) * scalar
        return t1

    def lorris_loss(self, true_point, predicted_max):
        buffer = self.lorris_buffer * self._fallof(self.lorris_decay)
        scalar = self.lorris * self._fallof(self.lorris_decay)

        diff = torch.sqrt(buffer + torch.relu(predicted_max - true_point + buffer))
        t1 = torch.square(torch.mean(diff)) * scalar

        return t1

    def step(self):
        self.step_num += 1
