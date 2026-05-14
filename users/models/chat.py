from django.db import models
from django.utils import timezone
from .user import User
from .itinerary import Itinerary


class Conversation(models.Model):
    """
    A direct chat between two users.
    We normalize user order (lowest id first) to ensure uniqueness.
    """
    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_user1')
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_user2')
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='conversations', null=True, blank=True)
    is_first_time = models.BooleanField(default=True, help_text="True if this is the first conversation between these users")
    is_free_for_creator = models.BooleanField(default=False, help_text="True if this connection is free for the itinerary creator (their first trip)")
    is_free_for_seeker = models.BooleanField(default=False, help_text="True if this connection is free for the seeker (their first seek)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user1', 'user2'],
                condition=models.Q(itinerary__isnull=True),
                name='unique_conversation_pair_without_itinerary'
            ),
            models.UniqueConstraint(
                fields=['user1', 'user2', 'itinerary'],
                name='unique_conversation_pair_per_itinerary'
            ),
        ]
        ordering = ['-updated_at']
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        seeker_to_mark = None

        # Normalize ordering so user1 id is always <= user2 id to avoid duplicates
        if self.user1_id and self.user2_id and self.user1_id > self.user2_id:
            self.user1, self.user2 = self.user2, self.user1

        # Set free flags once at creation when linked to an itinerary
        if is_new and self.itinerary_id:
            itinerary = self.itinerary
            creator_id = itinerary.user_id
            seeker = self.user1 if self.user2_id == creator_id else self.user2
            self.is_free_for_creator = itinerary.is_first_trip
            self.is_free_for_seeker = not seeker.has_used_free_seek
            if self.is_free_for_seeker:
                seeker_to_mark = seeker

        super().save(*args, **kwargs)

        if is_new and self.itinerary_id:
            from .itinerary_payment import ItineraryPayment
            from django.utils import timezone as tz

            itinerary = self.itinerary
            creator_id = itinerary.user_id
            seeker = self.user1 if self.user2_id == creator_id else self.user2
            creator = self.user2 if self.user2_id == creator_id else self.user1

            now = tz.now()
            creator_status = 'free' if self.is_free_for_creator else 'unpaid'
            seeker_status = 'free' if self.is_free_for_seeker else 'unpaid'

            # Creator: one record per itinerary (get_or_create so multiple seekers
            # connecting to the same itinerary don't create duplicate creator records)
            ItineraryPayment.objects.get_or_create(
                itinerary=itinerary,
                user=creator,
                defaults={
                    'role': 'creator',
                    'status': creator_status,
                    'paid_at': now if creator_status == 'free' else None,
                },
            )

            # Seeker: one record per itinerary connection, linked to the conversation
            ItineraryPayment.objects.get_or_create(
                itinerary=itinerary,
                user=seeker,
                defaults={
                    'role': 'seeker',
                    'conversation': self,
                    'status': seeker_status,
                    'paid_at': now if seeker_status == 'free' else None,
                },
            )

        # Consume the seeker's one free connection slot after the record is saved
        if seeker_to_mark is not None:
            User.objects.filter(pk=seeker_to_mark.pk).update(has_used_free_seek=True)

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


    def save(self, *args, **kwargs):
        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new and not self.sender.has_used_free_seek:
            User.objects.filter(pk=self.sender.pk).update(has_used_free_seek=True)

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
