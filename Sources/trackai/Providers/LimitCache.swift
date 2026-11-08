import Foundation

/// Polling discipline for a rate-limited usage endpoint: at most every 5 minutes,
/// at most once a minute even when forced, the last good result persisted across
/// restarts, exponential back-off on HTTP 429. Holds no tokens.
final class LimitCache {
    typealias Fetch = (String, @escaping (Result<ApiUsage, UsageAPIError>) -> Void) -> Void

    enum Outcome {
        case notDue
        case backingOff
        case fetched(ApiUsage)
        case failed(UsageAPIError)
    }

    private var cached: ApiUsage?
    private var backoffUntil = Date.distantPast
    private var consecutive429 = 0
    private var lastAttempt = Date.distantPast
    private var failure: String?
    private let freshness: TimeInterval = 300
    private let forceFloor: TimeInterval = 60
    private let lock = NSLock()
    private let persistKey: String

    init(persistKey: String) {
        self.persistKey = persistKey
    }

    /// The last good result, loading the persisted one on first use.
    func current() -> ApiUsage? {
        lock.lock()
        defer { lock.unlock() }
        loadPersistedIfNeeded()
        return cached
    }

    /// Why the latest fetch failed, until one succeeds.
    var lastError: String? {
        lock.lock()
        defer { lock.unlock() }
        return failure
    }

    func refresh(token: String?, force: Bool, fetch: Fetch, completion: @escaping (Outcome) -> Void) {
        let now = Date()

        lock.lock()
        loadPersistedIfNeeded()
        let inBackoff = backoffUntil > now
        let isFresh = cached.map { now.timeIntervalSince($0.fetchedAt) < freshness } ?? false
        // Even a manual refresh will not hammer the endpoint more than once a minute.
        let forceAllowed = now.timeIntervalSince(lastAttempt) > forceFloor
        let wantsFetch = force ? forceAllowed : !isFresh
        if wantsFetch && !inBackoff && token != nil { lastAttempt = now }
        lock.unlock()

        if inBackoff { completion(.backingOff); return }
        guard let token, wantsFetch else { completion(.notDue); return }

        fetch(token) { [self] result in
            switch result {
            case .success(let fresh):
                lock.lock()
                cached = fresh
                backoffUntil = .distantPast
                consecutive429 = 0
                failure = nil
                persist(fresh)
                lock.unlock()
                completion(.fetched(fresh))
            case .failure(let err):
                lock.lock()
                failure = err.description
                if case .rateLimited(let retryAfter) = err {
                    consecutive429 += 1
                    // 5 → 10 → 20 → 40 → 60 min, or Retry-After when it is longer.
                    var delay = min(3600, 300 * pow(2, Double(consecutive429 - 1)))
                    if let retryAfter, retryAfter > delay { delay = retryAfter }
                    backoffUntil = Date().addingTimeInterval(delay)
                }
                lock.unlock()
                completion(.failed(err))
            }
        }
    }

    private func loadPersistedIfNeeded() {
        guard cached == nil,
              let data = UserDefaults.standard.data(forKey: persistKey),
              let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let usage = ApiUsage.fromDict(dict) else { return }
        cached = usage
    }

    private func persist(_ usage: ApiUsage) {
        if let data = try? JSONSerialization.data(withJSONObject: usage.toDict()) {
            UserDefaults.standard.set(data, forKey: persistKey)
        }
    }
}
