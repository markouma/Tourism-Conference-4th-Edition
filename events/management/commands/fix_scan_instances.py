# your_app/management/commands/fix_scan_instances.py

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from events.models import ScanInstance, Event, TicketScanLog
from django.utils import timezone


class Command(BaseCommand):
    help = 'Fix scan instances that have missing or invalid event associations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--event-id',
            type=int,
            help='Specific event ID to assign to orphaned scan instances',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes',
        )
        parser.add_argument(
            '--create-defaults',
            action='store_true',
            help='Create default scan instances (Entrance, Meals 1, Meals 2) for events that don\'t have any',
        )
        parser.add_argument(
            '--clean-orphans',
            action='store_true',
            help='Remove scan instances that can\'t be associated with any event',
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🔧 Starting Scan Instance Fix Tool...\n')
        )

        # Check for issues
        self.check_scan_instance_issues()
        
        if options['create_defaults']:
            self.create_default_instances(options['dry_run'])
        
        if options['clean_orphans']:
            self.clean_orphaned_instances(options['dry_run'])
        else:
            self.fix_orphaned_instances(options['event_id'], options['dry_run'])
        
        self.check_scan_log_issues(options['dry_run'])
        
        self.stdout.write(
            self.style.SUCCESS('\n✅ Scan Instance Fix Tool completed!')
        )

    def check_scan_instance_issues(self):
        """Check and report scan instance issues"""
        self.stdout.write('📊 Checking scan instance issues...\n')
        
        # Count issues
        total_instances = ScanInstance.objects.count()
        orphaned_instances = ScanInstance.objects.filter(event__isnull=True).count()
        inactive_instances = ScanInstance.objects.filter(is_active=False).count()
        
        self.stdout.write(f'Total scan instances: {total_instances}')
        self.stdout.write(f'Orphaned instances (no event): {orphaned_instances}')
        self.stdout.write(f'Inactive instances: {inactive_instances}')
        
        if orphaned_instances > 0:
            self.stdout.write(
                self.style.WARNING(f'⚠️  Found {orphaned_instances} orphaned scan instances')
            )
            for instance in ScanInstance.objects.filter(event__isnull=True):
                self.stdout.write(f'   - {instance.name} (ID: {instance.id})')
        
        # Check events without scan instances
        events_without_instances = Event.objects.filter(scan_instances__isnull=True).distinct()
        if events_without_instances.exists():
            self.stdout.write(
                self.style.WARNING(f'⚠️  Found {events_without_instances.count()} events without scan instances')
            )
            for event in events_without_instances:
                self.stdout.write(f'   - {event.name} (ID: {event.id})')
        
        self.stdout.write('')

    def fix_orphaned_instances(self, event_id, dry_run):
        """Fix scan instances that don't have an event assigned"""
        orphaned = ScanInstance.objects.filter(event__isnull=True)
        
        if not orphaned.exists():
            self.stdout.write('✅ No orphaned scan instances found')
            return
        
        # Determine which event to use
        target_event = None
        if event_id:
            try:
                target_event = Event.objects.get(id=event_id)
            except Event.DoesNotExist:
                raise CommandError(f'Event with ID {event_id} does not exist')
        else:
            # Use the most recent event
            target_event = Event.objects.order_by('-date').first()
            if not target_event:
                raise CommandError('No events found in the system')
        
        self.stdout.write(f'🎯 Target event: {target_event.name} (ID: {target_event.id})')
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'[DRY RUN] Would fix {orphaned.count()} orphaned instances')
            )
            for instance in orphaned:
                self.stdout.write(f'   - Would assign {instance.name} to {target_event.name}')
        else:
            with transaction.atomic():
                fixed_count = 0
                for instance in orphaned:
                    instance.event = target_event
                    instance.save()
                    fixed_count += 1
                    self.stdout.write(f'✅ Fixed: {instance.name} → {target_event.name}')
                
                self.stdout.write(
                    self.style.SUCCESS(f'Fixed {fixed_count} orphaned scan instances')
                )

    def create_default_instances(self, dry_run):
        """Create default scan instances for events that don't have any"""
        default_instances = [
            ('Entrance', 'Main event entrance checkpoint'),
            ('Meals 1', 'First meal service checkpoint'), 
            ('Meals 2', 'Second meal service checkpoint')
        ]
        
        events_without_instances = Event.objects.filter(scan_instances__isnull=True).distinct()
        
        if not events_without_instances.exists():
            self.stdout.write('✅ All events have scan instances')
            return
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'[DRY RUN] Would create default instances for {events_without_instances.count()} events')
            )
            for event in events_without_instances:
                self.stdout.write(f'   - {event.name}: {len(default_instances)} instances')
        else:
            with transaction.atomic():
                created_count = 0
                for event in events_without_instances:
                    for name, description in default_instances:
                        instance, created = ScanInstance.objects.get_or_create(
                            name=name,
                            event=event,
                            defaults={
                                'description': description,
                                'is_active': True
                            }
                        )
                        if created:
                            created_count += 1
                            self.stdout.write(f'✅ Created: {name} for {event.name}')
                
                self.stdout.write(
                    self.style.SUCCESS(f'Created {created_count} default scan instances')
                )

    def clean_orphaned_instances(self, dry_run):
        """Remove scan instances that can't be associated with any event"""
        orphaned = ScanInstance.objects.filter(event__isnull=True)
        
        if not orphaned.exists():
            self.stdout.write('✅ No orphaned scan instances to clean')
            return
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'[DRY RUN] Would delete {orphaned.count()} orphaned instances')
            )
            for instance in orphaned:
                scan_count = instance.scan_logs.count() if hasattr(instance, 'scan_logs') else 0
                self.stdout.write(f'   - Would delete {instance.name} ({scan_count} scans)')
        else:
            # Check if any have scan logs
            instances_with_scans = []
            instances_without_scans = []
            
            for instance in orphaned:
                scan_count = instance.scan_logs.count() if hasattr(instance, 'scan_logs') else 0
                if scan_count > 0:
                    instances_with_scans.append((instance, scan_count))
                else:
                    instances_without_scans.append(instance)
            
            if instances_with_scans:
                self.stdout.write(
                    self.style.ERROR(f'❌ Cannot delete {len(instances_with_scans)} instances with scan history:')
                )
                for instance, count in instances_with_scans:
                    self.stdout.write(f'   - {instance.name} has {count} scans')
                self.stdout.write('   Use --event-id to assign them to an event instead')
            
            if instances_without_scans:
                with transaction.atomic():
                    deleted_count = len(instances_without_scans)
                    for instance in instances_without_scans:
                        self.stdout.write(f'🗑️  Deleted: {instance.name}')
                        instance.delete()
                    
                    self.stdout.write(
                        self.style.SUCCESS(f'Deleted {deleted_count} empty orphaned instances')
                    )

    def check_scan_log_issues(self, dry_run):
        """Check for scan logs with issues"""
        if not hasattr(TicketScanLog.objects.model, 'scan_instance'):
            return
            
        orphaned_logs = TicketScanLog.objects.filter(scan_instance__isnull=True)
        if orphaned_logs.exists():
            self.stdout.write(
                self.style.WARNING(f'⚠️  Found {orphaned_logs.count()} scan logs without scan instances')
            )
            if not dry_run:
                self.stdout.write('   Consider running data cleanup for these logs')

    def print_summary(self):
        """Print a summary of the current state"""
        self.stdout.write('\n📊 Current Scan Instance Summary:')
        self.stdout.write('-' * 40)
        
        for event in Event.objects.all():
            instance_count = event.scan_instances.count() if hasattr(event, 'scan_instances') else 0
            active_count = event.scan_instances.filter(is_active=True).count() if hasattr(event, 'scan_instances') else 0
            self.stdout.write(f'{event.name}: {active_count}/{instance_count} active instances')
        
        total_orphaned = ScanInstance.objects.filter(event__isnull=True).count()
        if total_orphaned > 0:
            self.stdout.write(f'Orphaned instances: {total_orphaned}')
        
        self.stdout.write('')