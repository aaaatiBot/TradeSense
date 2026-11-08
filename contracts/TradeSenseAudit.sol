// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TradeSenseAudit
 * @notice On-chain immutable audit anchoring for TradeSense recommendations and trade results.
 * @dev Complies with SRS §8 (FR-AUD).
 *
 * Requirements:
 * - Records cryptographic payload hashes before outcomes are known (ex-ante commitment).
 * - Disallows duplicate hash submissions.
 * - Emits indexed events for indexing and third-party verification.
 */
contract TradeSenseAudit {
    address public owner;
    mapping(address => bool) public authorizedWorkers;

    // Commitment mappings: payloadHash => block timestamp
    mapping(bytes32 => uint256) public recommendationAnchors;
    mapping(bytes32 => uint256) public tradeResultAnchors;

    // Events
    event RecommendationAnchored(
        bytes32 indexed payloadHash,
        address indexed submitter,
        uint256 blockTimestamp
    );

    event TradeResultAnchored(
        bytes32 indexed payloadHash,
        address indexed submitter,
        uint256 blockTimestamp
    );

    event WorkerAuthorized(address indexed worker, bool authorized);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // Custom Errors
    error ZeroHash();
    error AlreadyAnchored(bytes32 payloadHash);
    error UnauthorizedCaller();
    error ZeroAddress();

    modifier onlyAuthorized() {
        if (msg.sender != owner && !authorizedWorkers[msg.sender]) {
            revert UnauthorizedCaller();
        }
        _;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) {
            revert UnauthorizedCaller();
        }
        _;
    }

    constructor() {
        owner = msg.sender;
        authorizedWorkers[msg.sender] = true;
        emit WorkerAuthorized(msg.sender, true);
    }

    /**
     * @notice Anchor a recommendation payload hash.
     * @param payloadHash Keccak-256 hash of the canonical JSON recommendation payload.
     * @return timestamp Block timestamp at which anchor was committed.
     */
    function anchorRecommendation(bytes32 payloadHash) external onlyAuthorized returns (uint256) {
        if (payloadHash == bytes32(0)) revert ZeroHash();
        if (recommendationAnchors[payloadHash] != 0) revert AlreadyAnchored(payloadHash);

        uint256 ts = block.timestamp;
        recommendationAnchors[payloadHash] = ts;

        emit RecommendationAnchored(payloadHash, msg.sender, ts);
        return ts;
    }

    /**
     * @notice Anchor a trade result payload hash.
     * @param payloadHash Keccak-256 hash of the canonical JSON trade result payload.
     * @return timestamp Block timestamp at which anchor was committed.
     */
    function anchorTradeResult(bytes32 payloadHash) external onlyAuthorized returns (uint256) {
        if (payloadHash == bytes32(0)) revert ZeroHash();
        if (tradeResultAnchors[payloadHash] != 0) revert AlreadyAnchored(payloadHash);

        uint256 ts = block.timestamp;
        tradeResultAnchors[payloadHash] = ts;

        emit TradeResultAnchored(payloadHash, msg.sender, ts);
        return ts;
    }

    /**
     * @notice Check whether a recommendation payload hash has been anchored.
     */
    function verifyRecommendation(bytes32 payloadHash) external view returns (bool isAnchored, uint256 timestamp) {
        uint256 ts = recommendationAnchors[payloadHash];
        return (ts != 0, ts);
    }

    /**
     * @notice Check whether a trade result payload hash has been anchored.
     */
    function verifyTradeResult(bytes32 payloadHash) external view returns (bool isAnchored, uint256 timestamp) {
        uint256 ts = tradeResultAnchors[payloadHash];
        return (ts != 0, ts);
    }

    /**
     * @notice Set authorized worker address.
     */
    function setWorkerAuthorization(address worker, bool authorized) external onlyOwner {
        if (worker == address(0)) revert ZeroAddress();
        authorizedWorkers[worker] = authorized;
        emit WorkerAuthorized(worker, authorized);
    }

    /**
     * @notice Transfer contract ownership.
     */
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        address old = owner;
        owner = newOwner;
        emit OwnershipTransferred(old, newOwner);
    }
}
