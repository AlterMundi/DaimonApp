//! Shared application lifecycle, independent of any client transport.
//!
//! The receiving adapter supplies its existing owner/journal operations. This
//! runner neither owns another store nor admits input or funds model work.
use std::{future::Future, time::Duration};

use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Ownership {
    Held,
    Unavailable,
    Lost,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Recovery {
    OptionalProjection,
    NativeOutput,
    CanonicalAttention,
    KnownUnsentReturns,
    Artifacts,
}

pub(crate) trait Maintenance: Sync {
    fn renew_owner(&self) -> Ownership;
    fn recover(&self, phase: Recovery) -> impl Future<Output = ()> + Send;
}

pub(crate) async fn tick(owner: &impl Maintenance, shutdown: &CancellationToken) {
    if shutdown.is_cancelled() {
        return;
    }
    let ownership = owner.renew_owner();
    if ownership == Ownership::Lost {
        shutdown.cancel();
        return;
    }
    for phase in [
        Recovery::OptionalProjection,
        Recovery::NativeOutput,
        Recovery::CanonicalAttention,
        Recovery::KnownUnsentReturns,
        Recovery::Artifacts,
    ] {
        if shutdown.is_cancelled() {
            return;
        }
        if matches!(
            phase,
            Recovery::OptionalProjection | Recovery::CanonicalAttention
        ) && ownership != Ownership::Held
        {
            continue;
        }
        // Do not cancel a journal operation halfway through a possible external
        // effect. Each adapter retains its existing bounded recovery semantics.
        owner.recover(phase).await;
    }
}

pub(crate) async fn run(
    owner: &impl Maintenance,
    shutdown: &CancellationToken,
    interval: Duration,
) {
    assert!(
        !interval.is_zero(),
        "Backend heartbeat requires a nonzero interval"
    );
    loop {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => return,
            _ = tokio::time::sleep(interval) => {}
        }
        tick(owner, shutdown).await;
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use super::*;

    struct Owner {
        ownership: Ownership,
        seen: Mutex<Vec<Recovery>>,
        stop_after: Option<(Recovery, CancellationToken)>,
    }
    impl Maintenance for Owner {
        fn renew_owner(&self) -> Ownership {
            self.ownership
        }
        async fn recover(&self, phase: Recovery) {
            self.seen.lock().unwrap().push(phase);
            if let Some((selected, stop)) = &self.stop_after {
                if *selected == phase {
                    stop.cancel();
                }
            }
        }
    }
    fn owner(ownership: Ownership) -> Owner {
        Owner {
            ownership,
            seen: Mutex::new(vec![]),
            stop_after: None,
        }
    }

    #[tokio::test]
    async fn unavailable_owner_does_not_recover_external_projection() {
        let owner = owner(Ownership::Unavailable);
        tick(&owner, &CancellationToken::new()).await;
        assert_eq!(
            *owner.seen.lock().unwrap(),
            vec![
                Recovery::NativeOutput,
                Recovery::KnownUnsentReturns,
                Recovery::Artifacts
            ]
        );
    }

    #[tokio::test]
    async fn lost_owner_stops_before_any_recovery() {
        let owner = owner(Ownership::Lost);
        let stop = CancellationToken::new();
        tick(&owner, &stop).await;
        assert!(stop.is_cancelled());
        assert!(owner.seen.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn cancellation_between_operations_preserves_completed_work() {
        let stop = CancellationToken::new();
        let mut owner = owner(Ownership::Held);
        owner.stop_after = Some((Recovery::NativeOutput, stop.clone()));
        tick(&owner, &stop).await;
        tick(&owner, &stop).await;
        assert_eq!(
            *owner.seen.lock().unwrap(),
            vec![Recovery::OptionalProjection, Recovery::NativeOutput]
        );
    }

    #[tokio::test(start_paused = true)]
    async fn idle_wait_is_cancellable_without_starting_a_tick() {
        let owner = owner(Ownership::Held);
        let stop = CancellationToken::new();
        let task = run(&owner, &stop, Duration::from_secs(30));
        tokio::pin!(task);
        tokio::select! {
            biased;
            _ = &mut task => panic!("Not stopped yet"),
            _ = tokio::time::sleep(Duration::from_secs(1)) => {}
        }
        stop.cancel();
        task.await;
        assert!(owner.seen.lock().unwrap().is_empty());
    }
}
