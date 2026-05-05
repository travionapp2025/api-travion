from django.db import models
from django.utils import timezone
from .user import User


class Conversation(models.Model):
    """
    A direct chat between two users.
    We normalize user order (lowest id first) to ensure uniqueness.
    """
    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_user1')
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_user2')
    is_first_time = models.BooleanField(default=True, help_text="True if this is the first conversation between these users")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user1', 'user2'], name='unique_conversation_pair'),
        ]
        ordering = ['-updated_at']
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'

    def save(self, *args, **kwargs):
        # Normalize ordering so user1 id is always <= user2 id to avoid duplicates
        if self.user1_id and self.user2_id and self.user1_id > self.user2_id:
            self.user1, self.user2 = self.user2, self.user1
        super().save(*args, **kwargs)

    @property
    def participants(self):
        return [self.user1, self.user2]

    def __str__(self):
        return f"Conversation({self.user1.email}, {self.user2.email})"


class Message(models.Model):
    """
    Messages exchanged within a conversation.
    """
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        indexes = [
            models.Index(fields=['conversation', '-created_at'], name='msg_conv_time_idx'),
            models.Index(fields=['conversation', 'is_read'], name='msg_conv_read_idx'),
            models.Index(fields=['sender', '-created_at'], name='msg_sender_time_idx'),
        ]

    def __str__(self):
        return f"Msg[{self.id}] by {self.sender.email}: {self.content[:30]}"