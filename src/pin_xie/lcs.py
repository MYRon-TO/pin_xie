from __future__ import annotations


def lcs(a: list[str], b: list[str]) -> tuple[int, list[str]]:
    m = len(a)
    n = len(b)

    if m == 0 or n == 0:
        return 0, []

    dp: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = (
                    dp[i - 1][j] if dp[i - 1][j] >= dp[i][j - 1] else dp[i][j - 1]
                )

    i, j = m, n
    result: list[str] = []
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            result.append(a[i - 1])
            i -= 1
            j -= 1
            continue

        if dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    result.reverse()
    return dp[m][n], result
